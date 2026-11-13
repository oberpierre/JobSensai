import json
import logging
import os
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional
from urllib.parse import urlsplit

import redis
from sqlalchemy.orm import Session

from adapters.adapters._pay import pay_violation
from adapters.registry import AdapterRegistry
from scraper.database import SessionLocal, init_db
from scraper.ingest_events import record_ingest_failure
from scraper.models import (
    INGEST_REASON_INVALID_SHAPE,
    INGEST_REASON_NO_RULE,
    INGEST_REASON_RULE_RAISED,
    INGEST_REASON_UNPARSEABLE_CONTENT,
    INGEST_STAGE_DETAIL,
    JobPosting,
    RawJobPosting,
)

# The literal a Bronze row's content_type must equal to route to a detail mapping
# rather than an extraction adapter. The comparison is exact, so a value with
# parameters, such as "application/json; charset=utf-8", takes the extraction path.
_MAPPED_CONTENT_TYPE = "application/json"

# Not the learner's LEARNING_IN_PROGRESS lease, which would make it drop the task.
_DETAIL_REQUEST_KEY_PREFIX = "LEARNING_REQUESTED:detail:"
_DETAIL_REQUEST_TTL_SECONDS = 1800

# Required Silver fields, matching _save_job_posting's own blank check.
_REQUIRED_STRING_FIELDS = ("title", "company_name", "description")
_LIST_FIELDS = ("locations", "categories")


def _mapped_shape_violation(data: dict) -> Optional[str]:
    """Return what is wrong with a mapped Silver dict, or None if it is well-shaped.

    Called only after keys whose path resolved to None have been dropped, so an
    honestly absent optional field is never flagged here.
    """
    for field in _REQUIRED_STRING_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            return f"{field!r} must be a non-blank string"
    for field in _LIST_FIELDS:
        if field in data:
            value = data[field]
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                return f"{field!r} must be a list of strings"
    if "metadata" in data and not isinstance(data["metadata"], dict):
        return "'metadata' must be an object"
    if "employment_type" in data and not isinstance(data["employment_type"], str):
        return "'employment_type' must be a string"
    return None


def _without_empty_values(metadata: object) -> object:
    """*metadata* minus its top-level keys whose value is null or an empty string,
    list or object.
    """
    if not isinstance(metadata, dict):
        return metadata
    return {
        key: value
        for key, value in metadata.items()
        if not (value is None or value == "" or value == [] or value == {})
    }


def _pay_columns(pay: object, url: str) -> dict[str, object]:
    """The four pay column values for *pay*, all None unless it is a valid Silver
    pay.
    """
    violation = None if pay is None else pay_violation(pay)
    if pay is not None and violation is None:
        assert isinstance(pay, dict)
        return {
            "pay_min": pay["min"],
            "pay_max": pay["max"],
            "pay_currency": pay["currency"],
            "pay_period": pay["period"],
        }
    if pay is not None:
        logger.warning(f"Dropping invalid pay for {url}: {violation}")
    return {
        "pay_min": None,
        "pay_max": None,
        "pay_currency": None,
        "pay_period": None,
    }


# Configuration
@dataclass
class SilverWorkerConfig:
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", 6379))
    queue_name: str = "silver_generation_tasks"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SilverWorker:
    """Barebones Silver Worker that consumes silver_generation_tasks."""

    def __init__(self, config: SilverWorkerConfig):
        self.config = config
        self.should_exit = False
        self.redis: Optional[redis.Redis] = None
        self.registry = AdapterRegistry()

        # signal.signal only works on the main thread, so guard so construction off it
        # (test runners, thread pools) does not raise ValueError.
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except ValueError:
            logger.warning("Off the main thread; signal handlers not installed")

    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}. Shutting down safely...")
        self.should_exit = True

    def setup(self):
        """Initialize the database and connections."""
        # basicConfig ran at import with a fixed level, so honour config.log_level here.
        logging.getLogger().setLevel(self.config.log_level)
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
            decode_responses=True,
        )
        logger.info("Silver Worker setup complete.")

    def run(self):
        self.setup()
        logger.info(f"Worker started. Listening on queue '{self.config.queue_name}'...")

        while not self.should_exit:
            try:
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
                time.sleep(1)

        logger.info("Silver Worker shutdown complete.")

    def process_message(self, message: str):
        try:
            data = json.loads(message)
            url = data.get("url")

            if not url:
                logger.warning("Message missing URL, skipping.")
                return

            logger.info(f"Processing silver generation task for URL: {url}")

            # Establish database session
            db: Session = SessionLocal()
            try:
                # Fetch the raw job posting
                raw_job = (
                    db.query(RawJobPosting).filter(RawJobPosting.url == url).first()
                )
                if not raw_job:
                    logger.warning(f"RawJobPosting not found for URL: {url}")
                    return

                if raw_job.content_type == _MAPPED_CONTENT_TYPE:
                    self._process_mapped_row(db, url, raw_job)
                    return

                adapter = self.registry.get_extraction_adapter(url)
                if not adapter:
                    self._handle_missing_or_failed_adapter(url, raw_job.raw_content)
                    return

                try:
                    extracted_data = adapter.extract(raw_job.raw_content, url)

                    if not extracted_data:
                        raise ValueError("Extraction returned empty data")

                    self._save_job_posting(db, url, extracted_data)

                except Exception as e:
                    logger.error(f"Adapter extraction failed for URL {url}: {e}")
                    self._handle_missing_or_failed_adapter(url, raw_job.raw_content)

            finally:
                db.close()

        except json.JSONDecodeError:
            logger.error(f"Failed to decode message: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    def _process_mapped_row(
        self, db: Session, url: str, raw_job: RawJobPosting
    ) -> None:
        """Map a Bronze row whose content_type is JSON, validating its own output.

        Keyed on source_url rather than the posting's own url: an API posting's url
        is on the board's public host, whose extraction adapter (if any) would read
        a description fragment as a whole page. None of the four outcomes below
        shares process_message's HTML try/except, so a check failure here can never
        land in the same except as a database write failure.
        """
        hostname = urlsplit(raw_job.source_url).hostname
        try:
            document = json.loads(raw_job.raw_content)
        except ValueError as e:
            logger.error(
                f"raw_content for {hostname} (posting {url}) does not parse as "
                f"JSON: {e}"
            )
            record_ingest_failure(
                stage=INGEST_STAGE_DETAIL,
                reason=INGEST_REASON_UNPARSEABLE_CONTENT,
                source_url=raw_job.source_url,
                posting_url=url,
                start_url_id=raw_job.start_url_id,
                detail=str(e),
            )
            return
        if not isinstance(document, (dict, list)):
            logger.error(
                f"raw_content for {hostname} (posting {url}) parsed to "
                f"{type(document).__name__}, not an object or array"
            )
            record_ingest_failure(
                stage=INGEST_STAGE_DETAIL,
                reason=INGEST_REASON_UNPARSEABLE_CONTENT,
                source_url=raw_job.source_url,
                posting_url=url,
                start_url_id=raw_job.start_url_id,
                detail=type(document).__name__,
            )
            return

        mapping = self.registry.get_detail_mapping(raw_job.source_url)
        if mapping is None:
            logger.warning(
                f"No detail mapping for {hostname} (posting {url}); refused until "
                "one is learned"
            )
            record_ingest_failure(
                stage=INGEST_STAGE_DETAIL,
                reason=INGEST_REASON_NO_RULE,
                source_url=raw_job.source_url,
                posting_url=url,
                start_url_id=raw_job.start_url_id,
                detail=None,
            )
            self._request_detail_mapping(
                raw_job.source_url, hostname, raw_job.raw_content
            )
            return

        try:
            mapped = mapping.to_silver(document)
        except Exception as e:
            logger.error(f"detail mapping for {hostname} (posting {url}) raised: {e}")
            record_ingest_failure(
                stage=INGEST_STAGE_DETAIL,
                reason=INGEST_REASON_RULE_RAISED,
                source_url=raw_job.source_url,
                posting_url=url,
                start_url_id=raw_job.start_url_id,
                detail=str(e),
            )
            return

        # A declared key whose path resolved to None is dropped, so a mapping
        # honestly silent about a field fails the same way an absent one does.
        cleaned = {k: v for k, v in mapped.items() if v is not None}
        violation = _mapped_shape_violation(cleaned)
        if violation is not None:
            logger.error(
                f"mapped row for {hostname} (posting {url}) failed shape check: "
                f"{violation}"
            )
            record_ingest_failure(
                stage=INGEST_STAGE_DETAIL,
                reason=INGEST_REASON_INVALID_SHAPE,
                source_url=raw_job.source_url,
                posting_url=url,
                start_url_id=raw_job.start_url_id,
                detail=violation,
            )
            return

        self._save_job_posting(db, url, cleaned)

    def _request_detail_mapping(
        self, source_url: str, hostname: Optional[str], body: str
    ) -> None:
        """Ask the learner for a detail mapping, once per host per TTL."""
        if self.redis is None:
            logger.error(
                f"No Redis client; detail mapping learning task for {hostname} "
                "was not enqueued"
            )
            return

        if not hostname:
            logger.error(
                f"No hostname in {source_url}; detail mapping learning task "
                "was not enqueued"
            )
            return

        key = f"{_DETAIL_REQUEST_KEY_PREFIX}{hostname}"
        try:
            claimed = self.redis.set(key, "1", nx=True, ex=_DETAIL_REQUEST_TTL_SECONDS)
        except Exception as e:
            logger.error(
                f"Could not claim the detail mapping request for {hostname}, so the "
                f"learning task was not enqueued: {e}"
            )
            return
        if not claimed:
            return

        payload = {
            "artifact": "mapping",
            "domain": hostname,
            "url": source_url,
            "body": body,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        try:
            self.redis.lpush("extraction_learning_tasks", json.dumps(payload))
        except Exception as e:
            logger.error(
                f"Could not enqueue the detail mapping learning task for "
                f"{hostname}: {e}"
            )
            try:
                self.redis.delete(key)
            except Exception as delete_error:
                logger.error(
                    f"Could not release the request key for {hostname} "
                    f"({delete_error}), so the host waits out the TTL"
                )
            return
        logger.info(f"Enqueued a detail mapping learning task for {hostname}")

    def _save_job_posting(self, db: Session, url: str, data: dict):
        # title, company_name and description back NOT NULL columns. A missing one is a
        # broken extraction, so reject it here (it routes to re-learning) rather than
        # write a placeholder the UI would surface as a real posting.
        required = ("title", "company_name", "description")
        missing = [f for f in required if not data.get(f)]
        if missing:
            raise ValueError(f"extraction missing required fields {missing} for {url}")

        try:
            # Update or create the JobPosting
            job_posting = db.query(JobPosting).filter(JobPosting.url == url).first()
            if not job_posting:
                job_posting = JobPosting(url=url)
                db.add(job_posting)

            # Map extracted data to model
            job_posting.title = data["title"]
            job_posting.company_name = data["company_name"]
            job_posting.employment_type = data.get("employment_type")
            job_posting.locations = data.get("locations", [])
            job_posting.categories = data.get("categories", [])
            job_posting.description = data["description"]
            job_posting.metadata_ = _without_empty_values(data.get("metadata", {}))
            for column, value in _pay_columns(data.get("pay"), url).items():
                setattr(job_posting, column, value)

            db.commit()
            logger.info(f"Successfully saved JobPosting for URL: {url}")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to save JobPosting for URL {url}: {e}")
            raise

    def _handle_missing_or_failed_adapter(self, url: str, html: str):
        """Push to learning queue."""
        logger.info(f"Fallback triggered for URL: {url}. Sending to learning queue...")
        payload = {
            "url": url,
            "html_content": html,
        }
        if self.redis:
            self.redis.lpush("extraction_learning_tasks", json.dumps(payload))


if __name__ == "__main__":
    config = SilverWorkerConfig()
    worker = SilverWorker(config)
    worker.run()
