import json
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
    def test_html_row_no_extraction_adapter_pushes_to_learning_queue(
        self, mock_session_local
    ):
        """The control for the four JSON tests below that assert lpush was not
        called: an HTML row with no extraction adapter must still reach it."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        self.worker.registry.get_extraction_adapter = MagicMock(return_value=None)

        self._process(mock_db, self._raw_job("<html></html>", content_type="text/html"))

        self.worker.redis.lpush.assert_called_once_with(
            "extraction_learning_tasks",
            json.dumps({"url": self.POSTING_URL, "html_content": "<html></html>"}),
        )
        mock_db.commit.assert_not_called()

    @patch("scraper.silver_worker.SessionLocal")
    def test_html_extraction_employment_type_none_still_writes_row(
        self, mock_session_local
    ):
        """The mapped-row shape check never runs on this path: the committed
        Google adapter returns employment_type: None unconditionally today, and
        extraction only enforces title, company_name and description."""
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
        """A JSON scalar parses cleanly but is not a dict or list, so it is
        rejected the same way raw_content that fails to parse is."""
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
        # The row is added to the session but never persisted, which a mocked
        # db can only show through rollback having been called.
        mock_db.rollback.assert_called_once()
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
