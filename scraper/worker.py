import json
import logging
import os
import signal
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Optional

import redis
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scraper.database import SessionLocal, init_db
from scraper.models import RawJobPosting, ScraperRun


# Configuration
@dataclass
class WorkerConfig:
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", 6379))
    queue_name: str = "raw_job_items"
    silver_queue_name: str = "silver_generation_tasks"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class JobWorker:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.should_exit = False
        self.redis: Optional[redis.Redis] = None

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}. Shutting down safely...")
        self.should_exit = True

    def setup(self):
        """Initialize database and redis connections."""
        logger.info("Initializing database...")
        init_db()

        logger.info(
            f"Connecting to Redis: {self.config.redis_host}:{self.config.redis_port}..."
        )
        self.redis = redis.Redis(
            host=self.config.redis_host,
            port=self.config.redis_port,
            username=os.getenv("REDIS_USERNAME") or None,
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,  # Decode bytes to strings automatically
        )
        logger.info("Worker setup complete.")

    def run(self):
        self.setup()
        logger.info(f"Worker started. Listening on queue '{self.config.queue_name}'...")

        while not self.should_exit:
            try:
                # Use a timeout so we can check self.should_exit periodically
                # brpop returns a tuple (key, value)
                result = self.redis.brpop(self.config.queue_name, timeout=1)

                if not result:
                    continue

                _, message = result
                self.process_message(message)

            except redis.exceptions.ConnectionError:
                logger.error("Redis connection lost. Retrying in 5 seconds...")
                time.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                # Don't crash the worker, just sleep briefly
                time.sleep(1)

        logger.info("Worker shutdown complete.")

    def process_message(self, message: str):
        session = SessionLocal()
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "START_RUN":
                self._handle_start_run(session, data)
            elif msg_type == "ITEM":
                self._handle_item(session, data)
            elif msg_type == "END_OF_RUN":
                self._handle_end_run(session, data)
            else:
                logger.warning(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError:
            logger.error(f"Failed to decode message: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            session.rollback()
        finally:
            session.close()

    def _handle_start_run(self, session: Session, data: dict[str, Any]):
        client_run_id = data.get("run_id")
        spider_name = data.get("spider_name")
        if not client_run_id:
            logger.error("START_RUN missing run_id")
            return

        logger.info(f"Starting run {client_run_id} for spider {spider_name}")
        self._get_or_create_run(session, client_run_id, spider_name)

    def _handle_item(self, session: Session, data: dict[str, Any]):
        client_run_id = data.get("run_id")
        item = data.get("item", {})

        if not item or not client_run_id:
            logger.error("ITEM message missing valid item or run_id")
            return

        db_run_id = self._get_or_create_run(
            session, client_run_id, item.get("metadata", {}).get("spider", "unknown")
        )

        url = item.get("url")
        if not url:
            logger.warning("Item missing URL, skipping.")
            return

        raw_start_url_id = item.get("start_url_id")
        start_url_id = self._parse_start_url_id(raw_start_url_id)

        existing = session.execute(
            select(RawJobPosting).where(RawJobPosting.url == url)
        ).scalar_one_or_none()

        if existing:
            existing.updated_at = datetime.now(UTC)
            existing.last_seen_run_id = db_run_id
            existing.html_content = item.get("html_content")
            # Merge or overwrite metadata? Overwriting for now as it's "raw" state
            existing.metadata_ = item.get("metadata") or {}
            # First-writer-wins: a posting reachable from more than one start
            # URL keeps whichever one discovered it first, because the column
            # cannot express membership in two boards. The NULL check still
            # lets a backfill attribute a row older than this column.
            if raw_start_url_id and existing.start_url_id is None:
                existing.start_url_id = start_url_id
            if existing.deleted_at:
                logger.info(f"Reviving item: {url}")
                existing.deleted_at = None
        else:
            new_posting = RawJobPosting(
                url=url,
                html_content=item.get("html_content"),
                metadata_=item.get("metadata") or {},
                last_seen_run_id=db_run_id,
                start_url_id=start_url_id,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(new_posting)

        session.commit()

        # Push to silver generation queue
        if self.redis:
            self.redis.lpush(self.config.silver_queue_name, json.dumps({"url": url}))
            logger.debug(f"Pushed {url} to {self.config.silver_queue_name}")
        # logger.debug(f"Processed item: {url}")

    @staticmethod
    def _parse_start_url_id(raw_start_url_id: Any) -> Optional[uuid.UUID]:
        """The item carries start_url_id as a string, but the column needs a UUID."""
        if not raw_start_url_id:
            return None
        try:
            return uuid.UUID(raw_start_url_id)
        except ValueError:
            logger.warning(f"Invalid start_url_id on item: {raw_start_url_id!r}")
            return None

    def _handle_end_run(self, session: Session, data: dict[str, Any]):
        client_run_id = data.get("run_id")
        if not client_run_id:
            logger.error("END_OF_RUN is missing run_id")
            return
        logger.info(f"Run {client_run_id} finished. Initiating tombstoning.")

        db_run_id = self._get_or_create_run(
            session, client_run_id, data.get("spider_name", "unknown")
        )
        self._perform_tombstoning(session, db_run_id)

    def _get_or_create_run(
        self, session: Session, client_run_id: str, spider_name: str
    ):
        try:
            run_uuid = uuid.UUID(client_run_id)
        except ValueError:
            logger.error(f"Invalid UUID string: {client_run_id}")
            raise

        run = session.get(ScraperRun, run_uuid)
        if run:
            return run.id

        try:
            run = ScraperRun(id=run_uuid, spider_name=spider_name)
            session.add(run)
            session.commit()
            logger.info(f"Created new ScraperRun: {run.id}")
            return run.id
        except IntegrityError:
            session.rollback()
            # Race condition handling
            logger.info(
                f"Race condition detected for run {run_uuid}. Fetching existing."
            )
            run = session.get(ScraperRun, run_uuid)
            if run:
                return run.id
            raise

    def _perform_tombstoning(self, session: Session, current_run_id):
        """
        Marks items as deleted if they belong to the same spider but haven't been seen
        in the last 3 runs (including the current one).
        """
        current_run = session.get(ScraperRun, current_run_id)
        if not current_run:
            logger.error(f"Cannot tombstone: Run {current_run_id} not found.")
            return

        # Fetch the last 4 runs for this spider to determine the "unsafe" window
        # We need to find items that were last seen BEFORE the window of 3 runs.
        # Window: [Current, Last-1, Last-2].
        # Any item last seen in Last-3 or older is dead.

        history_stmt = (
            select(ScraperRun)
            .where(ScraperRun.spider_name == current_run.spider_name)
            .order_by(ScraperRun.started_at.desc())
            .limit(4)
        )

        recent_runs = session.execute(history_stmt).scalars().all()

        if len(recent_runs) < 4:
            logger.info(
                "Not enough history to perform tombstoning"
                " (need 4 runs to tombstone items from the 4th)."
            )
            return

        cutoff_date = recent_runs[2].started_at

        # We assume strict ordering of started_at. Tombstone anything where
        # last_seen_run_id implies a run started BEFORE the cutoff (safeguard).
        # Actually, if last_seen_run_id IS recent_runs[2].id, it is SAFE.
        # So we tombstone if run.started_at < recent_runs[2].started_at

        logger.info(
            f"Tombstoning items last seen before run"
            f" {recent_runs[2].id} ({cutoff_date})"
        )

        subquery = select(ScraperRun.id).where(
            ScraperRun.spider_name == current_run.spider_name,
            ScraperRun.started_at < cutoff_date,
        )

        stmt = (
            update(RawJobPosting)
            .where(
                RawJobPosting.deleted_at.is_(None),
                RawJobPosting.last_seen_run_id.in_(subquery),
            )
            .values(deleted_at=datetime.now(UTC))
        )

        result = session.execute(stmt)
        session.commit()
        logger.info(f"Tombstone complete. Marked {result.rowcount} items as deleted.")


if __name__ == "__main__":
    config = WorkerConfig()
    worker = JobWorker(config)
    worker.run()
