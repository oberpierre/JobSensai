import json
import os
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from scraper.models import RawJobPosting, ScraperRun
from scraper.worker import JobWorker, WorkerConfig


class TestJobWorker(unittest.TestCase):
    def setUp(self):
        self.config = WorkerConfig(
            redis_host="localhost",
            redis_port=6379,
            queue_name="test_queue",
            silver_queue_name="silver_generation_tasks",
            log_level="ERROR",
        )
        self.worker = JobWorker(self.config)

        # Mock Redis
        self.worker.redis = MagicMock()

        # Mock Database Session
        self.mock_session = MagicMock()
        self.session_patcher = patch(
            "scraper.worker.SessionLocal", return_value=self.mock_session
        )
        self.session_patcher.start()

    def tearDown(self):
        self.session_patcher.stop()

    def test_process_message_start_run(self):
        run_id = str(uuid.uuid4())
        message = json.dumps(
            {"type": "START_RUN", "run_id": run_id, "spider_name": "test_spider"}
        )

        # Setup run lookup to return None (so it creates one)
        self.mock_session.get.return_value = None

        self.worker.process_message(message)

        # Verify run creation
        self.mock_session.add.assert_called_once()
        added_run = self.mock_session.add.call_args[0][0]
        self.assertIsInstance(added_run, ScraperRun)
        self.assertEqual(str(added_run.id), run_id)
        self.assertEqual(added_run.spider_name, "test_spider")
        self.mock_session.commit.assert_called_once()
        self.mock_session.close.assert_called_once()

    def test_process_message_item(self):
        run_id = str(uuid.uuid4())
        item_url = "http://example.com/job/1"
        message = json.dumps(
            {
                "type": "ITEM",
                "run_id": run_id,
                "item": {
                    "url": item_url,
                    "html_content": "<html></html>",
                    "metadata": {"spider": "test_spider"},
                },
            }
        )

        # Setup run lookup to return valid run
        mock_run = ScraperRun(id=uuid.UUID(run_id), spider_name="test_spider")
        self.mock_session.get.return_value = mock_run

        # Setup existing item lookup to return None (new item)
        self.mock_session.execute.return_value.scalar_one_or_none.return_value = None

        self.worker.process_message(message)

        # Verify item creation
        self.mock_session.add.assert_called()
        # First add might be run (if get is called internally again) or item
        # In current logic: _get_or_create_run calls session.get -> returns mock_run
        # handle_item -> calls session.add(new_posting)

        added_items = [args[0] for args, _ in self.mock_session.add.call_args_list]
        job_item = next((i for i in added_items if isinstance(i, RawJobPosting)), None)
        self.assertIsNotNone(job_item)
        self.assertEqual(job_item.url, item_url)
        self.assertEqual(job_item.last_seen_run_id, uuid.UUID(run_id))

        # Verify pushing to silver queue
        self.worker.redis.lpush.assert_called_once_with(
            "silver_generation_tasks", json.dumps({"url": item_url})
        )

    def test_process_message_item_insert_persists_start_url_id(self):
        run_id = str(uuid.uuid4())
        start_url_id = uuid.uuid4()
        item_url = "http://example.com/job/1"
        message = json.dumps(
            {
                "type": "ITEM",
                "run_id": run_id,
                "item": {
                    "url": item_url,
                    "html_content": "<html></html>",
                    "metadata": {"spider": "test_spider"},
                    "start_url_id": str(start_url_id),
                },
            }
        )

        mock_run = ScraperRun(id=uuid.UUID(run_id), spider_name="test_spider")
        self.mock_session.get.return_value = mock_run
        self.mock_session.execute.return_value.scalar_one_or_none.return_value = None

        self.worker.process_message(message)

        added_items = [args[0] for args, _ in self.mock_session.add.call_args_list]
        job_item = next((i for i in added_items if isinstance(i, RawJobPosting)), None)
        self.assertIsNotNone(job_item)
        self.assertEqual(job_item.start_url_id, start_url_id)

    def test_process_message_item_update_persists_start_url_id(self):
        run_id = str(uuid.uuid4())
        start_url_id = uuid.uuid4()
        item_url = "http://example.com/job/1"
        message = json.dumps(
            {
                "type": "ITEM",
                "run_id": run_id,
                "item": {
                    "url": item_url,
                    "html_content": "<html></html>",
                    "metadata": {"spider": "test_spider"},
                    "start_url_id": str(start_url_id),
                },
            }
        )

        mock_run = ScraperRun(id=uuid.UUID(run_id), spider_name="test_spider")
        self.mock_session.get.return_value = mock_run

        existing_posting = RawJobPosting(
            url=item_url, html_content="<html>old</html>", start_url_id=None
        )
        self.mock_session.execute.return_value.scalar_one_or_none.return_value = (
            existing_posting
        )

        self.worker.process_message(message)

        self.assertEqual(existing_posting.start_url_id, start_url_id)

    def test_tombstoning_logic(self):
        # Current run
        current_run_id = uuid.uuid4()
        current_run = ScraperRun(
            id=current_run_id, spider_name="test_spider", started_at=datetime.now(UTC)
        )

        # History setup: [Current, R-1, R-2, R-3]
        # We need R-2 as safe cutoff.
        r1 = ScraperRun(
            id=uuid.uuid4(),
            spider_name="test_spider",
            started_at=datetime.now(UTC) - timedelta(hours=1),
        )
        r2 = ScraperRun(
            id=uuid.uuid4(),
            spider_name="test_spider",
            started_at=datetime.now(UTC) - timedelta(hours=2),
        )
        r3 = ScraperRun(
            id=uuid.uuid4(),
            spider_name="test_spider",
            started_at=datetime.now(UTC) - timedelta(hours=3),
        )

        history = [current_run, r1, r2, r3]

        # Mock session.get to return current run
        self.mock_session.get.return_value = current_run

        # Mock history query result
        self.mock_session.execute.return_value.scalars.return_value.all.return_value = (
            history
        )

        self.worker._perform_tombstoning(self.mock_session, current_run_id)

        # Verify update statement execution
        # Logic: update RawJobPosting where last_seen in subquery
        self.mock_session.execute.assert_called()

        # We expect at least 2 execute calls: 1 for select history, 1 for update
        # Check if update was called
        calls = self.mock_session.execute.call_args_list
        update_call = None
        for call in calls:
            # sqlalchemy update() returns an Update object, checked via str()
            # or type usually. But here we pass it to execute.
            arg = call[0][0]
            if str(arg).startswith("UPDATE raw_job_postings"):
                update_call = call

        self.assertIsNotNone(
            update_call, "Update statement for tombstoning not executed"
        )

    def test_invalid_uuid(self):
        # Should log error and not crash
        message = json.dumps(
            {"type": "START_RUN", "run_id": "not-a-uuid", "spider_name": "test"}
        )
        self.worker.process_message(message)
        # Should handle exception internally and close session
        self.mock_session.close.assert_called()

    def test_end_run_missing_run_id(self):
        # A missing run_id must be rejected before uuid.UUID(None) raises TypeError.
        self.worker._get_or_create_run = MagicMock()
        self.worker.process_message(json.dumps({"type": "END_OF_RUN"}))
        self.worker._get_or_create_run.assert_not_called()
        self.mock_session.close.assert_called()

    @patch("scraper.worker.init_db")
    @patch("scraper.worker.redis.Redis")
    def test_setup_passes_credentials_from_env(self, mock_redis, _mock_init_db):
        with patch.dict(
            os.environ, {"REDIS_USERNAME": "user", "REDIS_PASSWORD": "password"}
        ):
            JobWorker(self.config).setup()
        self.assertEqual(mock_redis.call_args.kwargs["username"], "user")
        self.assertEqual(mock_redis.call_args.kwargs["password"], "password")

    @patch("scraper.worker.init_db")
    @patch("scraper.worker.redis.Redis")
    def test_setup_passes_none_credentials_when_unset(self, mock_redis, _mock_init_db):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_USERNAME", None)
            os.environ.pop("REDIS_PASSWORD", None)
            JobWorker(self.config).setup()
        self.assertIsNone(mock_redis.call_args.kwargs["username"])
        self.assertIsNone(mock_redis.call_args.kwargs["password"])


if __name__ == "__main__":
    unittest.main()
