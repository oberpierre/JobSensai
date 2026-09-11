import json
import logging
import os
import threading
import unittest
from unittest.mock import MagicMock, patch

from scraper.models import RawJobPosting
from scraper.silver_worker import SilverWorker, SilverWorkerConfig


def _query_first_factory(raw_job):
    """A ``db.query(...).filter(...).first()`` double returning *raw_job* for
    RawJobPosting queries and None otherwise, matching the JobPosting
    existence check SilverWorker itself runs before creating a new row.
    """

    def query_first(model):
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = raw_job if model == RawJobPosting else None
        mock_query.filter.return_value = mock_filter
        return mock_query

    return query_first


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
                    url="https://google.com/job/1", raw_content="<html></html>"
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
        """A missing NOT NULL field must not be written, so it routes to re-learning."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.query().filter().first.return_value = RawJobPosting(
            url="https://google.com/job/1", raw_content="<html></html>"
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
            url="https://unknown.com/job/1", raw_content="<html></html>"
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
        """signal.signal raises off the main thread, so construction must survive it."""
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


class TestSilverWorkerMappedRows(unittest.TestCase):
    """The JSON branch: mapped by source_url, validated before it reaches Silver."""

    SOURCE_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    POSTING_URL = "https://boards.greenhouse.io/acme/jobs/123"

    def setUp(self):
        self.config = SilverWorkerConfig(
            redis_host="localhost",
            redis_port=6379,
            queue_name="test_silver_queue",
            log_level="ERROR",
        )
        self.worker = SilverWorker(self.config)
        self.worker.redis = MagicMock()

    def _raw_job(self, raw_content, content_type="application/json"):
        return RawJobPosting(
            url=self.POSTING_URL,
            source_url=self.SOURCE_URL,
            content_type=content_type,
            raw_content=raw_content,
        )

    def _process(self, mock_db, raw_job):
        mock_db.query.side_effect = _query_first_factory(raw_job)
        self.worker.process_message(json.dumps({"url": self.POSTING_URL}))

    @patch("scraper.silver_worker.SessionLocal")
    def test_json_row_maps_by_source_url_not_url(self, mock_session_local):
        """An API posting's own url resolves to the board's HTML extraction
        adapter; keying the lookup on source_url instead is the whole point."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_mapping = MagicMock()
        mock_mapping.to_silver.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
        }
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)
        self.worker.registry.get_extraction_adapter = MagicMock()

        self._process(mock_db, self._raw_job(json.dumps({"title": "Engineer"})))

        self.worker.registry.get_detail_mapping.assert_called_once_with(self.SOURCE_URL)
        self.worker.registry.get_extraction_adapter.assert_not_called()
        mock_db.commit.assert_called_once()

    @patch("scraper.silver_worker.SessionLocal")
    def test_html_row_takes_extraction_path_unchanged(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_adapter = MagicMock()
        mock_adapter.extract.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
        }
        self.worker.registry.get_extraction_adapter = MagicMock(
            return_value=mock_adapter
        )
        self.worker.registry.get_detail_mapping = MagicMock()

        self._process(mock_db, self._raw_job("<html></html>", content_type="text/html"))

        self.worker.registry.get_extraction_adapter.assert_called_once()
        self.worker.registry.get_detail_mapping.assert_not_called()
        mock_db.commit.assert_called_once()

    @patch("scraper.silver_worker.SessionLocal")
    def test_content_type_with_parameters_takes_extraction_path(
        self, mock_session_local
    ):
        """The comparison is exact, so a literal-plus-parameters value is not the
        mapped path's literal, proving this is not a substring check."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_adapter = MagicMock()
        mock_adapter.extract.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
        }
        self.worker.registry.get_extraction_adapter = MagicMock(
            return_value=mock_adapter
        )
        self.worker.registry.get_detail_mapping = MagicMock()

        self._process(
            mock_db,
            self._raw_job(
                "<html></html>", content_type="application/json; charset=utf-8"
            ),
        )

        self.worker.registry.get_extraction_adapter.assert_called_once()
        self.worker.registry.get_detail_mapping.assert_not_called()

    @patch("scraper.silver_worker.SessionLocal")
    def test_html_extraction_employment_type_none_still_writes_row(
        self, mock_session_local
    ):
        """Proves the shape check P6 adds stayed on the JSON side: the committed
        Google adapter returns employment_type: None unconditionally today."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_adapter = MagicMock()
        mock_adapter.extract.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "employment_type": None,
            "locations": [],
            "categories": [],
            "description": "Build things",
            "metadata": {},
        }
        self.worker.registry.get_extraction_adapter = MagicMock(
            return_value=mock_adapter
        )

        self._process(mock_db, self._raw_job("<html></html>", content_type="text/html"))

        mock_db.commit.assert_called_once()

    @patch("scraper.silver_worker.SessionLocal")
    def test_json_row_no_detail_mapping_writes_nothing(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        self.worker.registry.get_detail_mapping = MagicMock(return_value=None)

        self._process(mock_db, self._raw_job(json.dumps({"title": "Engineer"})))

        mock_db.commit.assert_not_called()
        mock_db.add.assert_not_called()
        self.worker.redis.lpush.assert_not_called()

    @patch("scraper.silver_worker.SessionLocal")
    def test_json_row_malformed_raw_content_writes_nothing(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        self.worker.registry.get_detail_mapping = MagicMock(return_value=MagicMock())

        self._process(mock_db, self._raw_job("not json at all"))

        mock_db.commit.assert_not_called()
        mock_db.add.assert_not_called()
        self.worker.redis.lpush.assert_not_called()

    @patch("scraper.silver_worker.SessionLocal")
    def test_json_row_scalar_raw_content_writes_nothing(self, mock_session_local):
        """A JSON scalar parses cleanly but is not dict | list, Shared contracts'
        document type, so it is the same outcome as raw_content failing to parse."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        self.worker.registry.get_detail_mapping = MagicMock(return_value=MagicMock())

        self._process(mock_db, self._raw_job(json.dumps("maintenance")))

        mock_db.commit.assert_not_called()
        mock_db.add.assert_not_called()
        self.worker.redis.lpush.assert_not_called()

    @patch("scraper.silver_worker.SessionLocal")
    def test_json_row_to_silver_raising_writes_nothing(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_mapping = MagicMock()
        mock_mapping.to_silver.side_effect = Exception(
            "markdown() argument must be a string"
        )
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)

        self._process(mock_db, self._raw_job(json.dumps({"title": "Engineer"})))

        mock_db.commit.assert_not_called()
        mock_db.add.assert_not_called()
        self.worker.redis.lpush.assert_not_called()

    @patch("scraper.silver_worker.SessionLocal")
    def test_json_row_blank_required_field_writes_nothing(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_mapping = MagicMock()
        mock_mapping.to_silver.return_value = {
            "title": "",
            "company_name": "Acme",
            "description": "Build things",
        }
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)

        self._process(mock_db, self._raw_job(json.dumps({"title": ""})))

        mock_db.commit.assert_not_called()
        mock_db.add.assert_not_called()
        self.worker.redis.lpush.assert_not_called()

    @patch("scraper.silver_worker.SessionLocal")
    def test_json_row_locations_as_bare_string_writes_nothing(self, mock_session_local):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_mapping = MagicMock()
        mock_mapping.to_silver.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
            "locations": "Zurich",
        }
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)

        self._process(mock_db, self._raw_job(json.dumps({"title": "Engineer"})))

        mock_db.commit.assert_not_called()
        mock_db.add.assert_not_called()

    @patch("scraper.silver_worker.SessionLocal")
    def test_json_row_locations_resolving_to_none_writes_empty_list(
        self, mock_session_local
    ):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_mapping = MagicMock()
        mock_mapping.to_silver.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
            "locations": None,
        }
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)

        self._process(mock_db, self._raw_job(json.dumps({"title": "Engineer"})))

        mock_db.commit.assert_called_once()
        saved = mock_db.add.call_args[0][0]
        self.assertEqual(saved.locations, [])

    @patch("scraper.silver_worker.SessionLocal")
    def test_json_row_database_write_failure_not_treated_as_mapping_failure(
        self, mock_session_local
    ):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_mapping = MagicMock()
        mock_mapping.to_silver.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
        }
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)
        mock_db.commit.side_effect = Exception("connection reset")
        self.worker._handle_missing_or_failed_adapter = MagicMock()

        with self.assertLogs("scraper.silver_worker", level="ERROR") as captured:
            self._process(mock_db, self._raw_job(json.dumps({"title": "Engineer"})))

        self.worker._handle_missing_or_failed_adapter.assert_not_called()
        mapping_failure_phrases = (
            "No detail mapping",
            "does not parse as",
            "raised:",
            "failed shape check",
        )
        self.assertFalse(
            any(
                phrase in message
                for message in captured.output
                for phrase in mapping_failure_phrases
            )
        )


if __name__ == "__main__":
    unittest.main()
