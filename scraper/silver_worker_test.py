import json
import logging
import os
import threading
import unittest
from unittest.mock import MagicMock, patch

from scraper.models import RawJobPosting
from scraper.silver_worker import SilverWorker, SilverWorkerConfig


class TestSilverWorker(unittest.TestCase):
    def setUp(self):
        self.config = SilverWorkerConfig(
            redis_host="localhost",
            redis_port=6379,
            queue_name="test_silver_queue",
            log_level="ERROR",
        )
        self.worker = SilverWorker(self.config)
        self.worker.redis = MagicMock()

    @patch("scraper.silver_worker.SessionLocal")
    def test_process_message_valid(self, mock_session_local):
        # Slice 2: Mock database and adapter extraction.
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        # Force JobPosting query to return None so it creates and adds a new one
        def mock_query_first(model):
            mock_query = MagicMock()
            mock_filter = MagicMock()
            if model == RawJobPosting:
                mock_filter.first.return_value = RawJobPosting(
                    url="https://google.com/job/1", html_content="<html></html>"
                )
            else:
                mock_filter.first.return_value = None
            mock_query.filter.return_value = mock_filter
            return mock_query

        mock_db.query.side_effect = mock_query_first

        mock_adapter = MagicMock()
        mock_adapter.extract.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
        }
        self.worker.registry.get_extraction_adapter = MagicMock(
            return_value=mock_adapter
        )

        message = json.dumps({"url": "https://google.com/job/1"})

        try:
            self.worker.process_message(message)
        except Exception as e:
            self.fail(f"process_message raised Exception unexpectedly: {e}")

        # Verify save was called implicitly
        mock_db.add.assert_called()
        mock_db.commit.assert_called()

    @patch("scraper.silver_worker.SessionLocal")
    def test_process_message_missing_required_field_routes_to_learning(
        self, mock_session_local
    ):
        """A missing NOT NULL field must not be written — it routes to re-learning."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.query().filter().first.return_value = RawJobPosting(
            url="https://google.com/job/1", html_content="<html></html>"
        )

        mock_adapter = MagicMock()
        # No company_name / description → cannot satisfy the NOT NULL columns.
        mock_adapter.extract.return_value = {"title": "Engineer"}
        self.worker.registry.get_extraction_adapter = MagicMock(
            return_value=mock_adapter
        )
        self.worker._handle_missing_or_failed_adapter = MagicMock()

        self.worker.process_message(json.dumps({"url": "https://google.com/job/1"}))

        self.worker._handle_missing_or_failed_adapter.assert_called_once()
        mock_db.commit.assert_not_called()

    @patch("scraper.silver_worker.SessionLocal")
    def test_process_message_adapter_missing_calls_fallback(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        mock_raw_job = RawJobPosting(
            url="https://unknown.com/job/1", html_content="<html></html>"
        )
        mock_db.query().filter().first.return_value = mock_raw_job

        self.worker.registry.get_extraction_adapter = MagicMock(return_value=None)
        self.worker._handle_missing_or_failed_adapter = MagicMock()

        message = json.dumps({"url": "https://unknown.com/job/1"})
        self.worker.process_message(message)

        self.worker._handle_missing_or_failed_adapter.assert_called_once_with(
            "https://unknown.com/job/1", "<html></html>"
        )

    def test_process_message_missing_url(self):
        message = json.dumps({"other_data": "test"})

        # Should handle silently for now
        self.worker.process_message(message)

    def test_process_message_invalid_json(self):
        message = "invalid json"

        # Should catch JSONDecodeError internally
        self.worker.process_message(message)

    def test_construction_off_the_main_thread_does_not_raise(self):
        """signal.signal raises off the main thread; construction must survive it."""
        errors = []

        def build():
            try:
                SilverWorker(SilverWorkerConfig())
            except Exception as exc:  # noqa: BLE001 — the point is to catch any raise
                errors.append(exc)

        thread = threading.Thread(target=build)
        thread.start()
        thread.join()

        self.assertEqual(errors, [])

    @patch("scraper.silver_worker.init_db")
    @patch("scraper.silver_worker.redis.Redis")
    def test_setup_applies_configured_log_level(self, _mock_redis, _mock_init_db):
        root = logging.getLogger()
        self.addCleanup(root.setLevel, root.level)
        root.setLevel(logging.INFO)

        SilverWorker(SilverWorkerConfig(log_level="ERROR")).setup()

        self.assertEqual(root.level, logging.ERROR)

    @patch("scraper.silver_worker.init_db")
    @patch("scraper.silver_worker.redis.Redis")
    def test_setup_initialises_the_database(self, _mock_redis, mock_init_db):
        SilverWorker(SilverWorkerConfig()).setup()
        mock_init_db.assert_called_once()

    @patch("scraper.silver_worker.init_db")
    @patch("scraper.silver_worker.redis.Redis")
    def test_setup_passes_credentials_from_env(self, mock_redis, _mock_init_db):
        with patch.dict(
            os.environ, {"REDIS_USERNAME": "user", "REDIS_PASSWORD": "password"}
        ):
            SilverWorker(SilverWorkerConfig()).setup()
        self.assertEqual(mock_redis.call_args.kwargs["username"], "user")
        self.assertEqual(mock_redis.call_args.kwargs["password"], "password")

    @patch("scraper.silver_worker.init_db")
    @patch("scraper.silver_worker.redis.Redis")
    def test_setup_passes_none_credentials_when_unset(self, mock_redis, _mock_init_db):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_USERNAME", None)
            os.environ.pop("REDIS_PASSWORD", None)
            SilverWorker(SilverWorkerConfig()).setup()
        self.assertIsNone(mock_redis.call_args.kwargs["username"])
        self.assertIsNone(mock_redis.call_args.kwargs["password"])


if __name__ == "__main__":
    unittest.main()
