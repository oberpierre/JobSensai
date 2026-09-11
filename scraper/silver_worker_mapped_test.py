import json
import unittest
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from scraper.models import (
    INGEST_REASON_INVALID_SHAPE,
    INGEST_REASON_NO_RULE,
    INGEST_REASON_RULE_RAISED,
    INGEST_REASON_UNPARSEABLE_CONTENT,
    INGEST_STAGE_DETAIL,
    Base,
    IngestEvent,
    JobPosting,
    RawJobPosting,
)
from scraper.silver_worker import SilverWorker, SilverWorkerConfig


# sqlite has no JSONB/UUID types, and Base.metadata.create_all() would fail
# against it otherwise. Rendering them as TEXT is safe because only row
# persistence is under test here, not the columns' real types.
@compiles(JSONB, "sqlite")
@compiles(UUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


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
    """The JSON branch: mapped by source_url, validated before it reaches Silver.

    These cases only need to prove which branch ran, so a MagicMock session
    is enough: nothing here depends on whether a write would really survive.
    """

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
        """The control for the JSON tests below that assert lpush was not
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


class TestSilverWorkerIngestEvents(unittest.TestCase):
    """Whether a refusal really reaches ingest_events, and Silver really does not.

    A MagicMock session records that ``add`` was called whether or not the
    insert would have survived, so a NotNullViolation on every write would
    leave every such assertion green with the table empty. These run
    SilverWorker against a real SQLite session instead, with both
    SessionLocal names patched to it so the worker and the recorder it calls
    write to the same database.
    """

    SOURCE_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    POSTING_URL = "https://boards.greenhouse.io/acme/jobs/123"
    DOMAIN = "boards-api.greenhouse.io"

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)

        for target in (
            "scraper.silver_worker.SessionLocal",
            "scraper.ingest_events.SessionLocal",
        ):
            patcher = patch(target, self.SessionLocal)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.config = SilverWorkerConfig(
            redis_host="localhost",
            redis_port=6379,
            queue_name="test_silver_queue",
            log_level="ERROR",
        )
        self.worker = SilverWorker(self.config)
        self.worker.redis = MagicMock()
        self.start_url_id = uuid.uuid4()

    def _seed_raw_job(self, raw_content, url=None, content_type="application/json"):
        session = self.SessionLocal()
        session.add(
            RawJobPosting(
                url=url or self.POSTING_URL,
                source_url=self.SOURCE_URL,
                content_type=content_type,
                raw_content=raw_content,
                start_url_id=self.start_url_id,
            )
        )
        session.commit()
        session.close()

    def _process(self, url=None):
        self.worker.process_message(json.dumps({"url": url or self.POSTING_URL}))

    def test_no_detail_mapping_records_no_rule(self):
        self._seed_raw_job(json.dumps({"title": "Engineer"}))
        self.worker.registry.get_detail_mapping = MagicMock(return_value=None)

        self._process()

        session = self.SessionLocal()
        (event,) = session.query(IngestEvent).all()
        self.assertEqual(event.reason, INGEST_REASON_NO_RULE)
        self.assertEqual(event.stage, INGEST_STAGE_DETAIL)
        self.assertEqual(event.start_url_id, self.start_url_id)
        self.assertEqual(event.domain, self.DOMAIN)
        self.assertEqual(event.posting_url, self.POSTING_URL)
        self.assertIsNone(
            session.query(JobPosting).filter(JobPosting.url == self.POSTING_URL).first()
        )

    def test_unparseable_raw_content_records_unparseable_content(self):
        self._seed_raw_job("not json at all")
        self.worker.registry.get_detail_mapping = MagicMock(return_value=MagicMock())

        self._process()

        session = self.SessionLocal()
        (event,) = session.query(IngestEvent).all()
        self.assertEqual(event.reason, INGEST_REASON_UNPARSEABLE_CONTENT)
        self.assertEqual(event.start_url_id, self.start_url_id)
        self.assertEqual(event.domain, self.DOMAIN)
        self.assertEqual(event.posting_url, self.POSTING_URL)
        self.assertIsNone(
            session.query(JobPosting).filter(JobPosting.url == self.POSTING_URL).first()
        )

    def test_scalar_raw_content_writes_no_silver_row(self):
        """A JSON scalar parses cleanly but is not a dict or list, so it is
        rejected the same way raw_content that fails to parse is."""
        self._seed_raw_job(json.dumps("maintenance"))
        self.worker.registry.get_detail_mapping = MagicMock(return_value=MagicMock())

        self._process()

        session = self.SessionLocal()
        self.assertIsNone(
            session.query(JobPosting).filter(JobPosting.url == self.POSTING_URL).first()
        )

    def test_to_silver_raising_records_rule_raised(self):
        self._seed_raw_job(json.dumps({"title": "Engineer"}))
        mock_mapping = MagicMock()
        mock_mapping.to_silver.side_effect = Exception(
            "markdown() argument must be a string"
        )
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)

        self._process()

        session = self.SessionLocal()
        (event,) = session.query(IngestEvent).all()
        self.assertEqual(event.reason, INGEST_REASON_RULE_RAISED)
        self.assertEqual(event.start_url_id, self.start_url_id)
        self.assertEqual(event.domain, self.DOMAIN)
        self.assertEqual(event.posting_url, self.POSTING_URL)
        self.assertIsNone(
            session.query(JobPosting).filter(JobPosting.url == self.POSTING_URL).first()
        )

    def test_blank_required_field_records_invalid_shape(self):
        self._seed_raw_job(json.dumps({"title": ""}))
        mock_mapping = MagicMock()
        mock_mapping.to_silver.return_value = {
            "title": "",
            "company_name": "Acme",
            "description": "Build things",
        }
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)

        self._process()

        session = self.SessionLocal()
        (event,) = session.query(IngestEvent).all()
        self.assertEqual(event.reason, INGEST_REASON_INVALID_SHAPE)
        self.assertEqual(event.start_url_id, self.start_url_id)
        self.assertEqual(event.domain, self.DOMAIN)
        self.assertEqual(event.posting_url, self.POSTING_URL)
        self.assertIsNone(
            session.query(JobPosting).filter(JobPosting.url == self.POSTING_URL).first()
        )

    def test_locations_as_bare_string_writes_no_silver_row(self):
        self._seed_raw_job(json.dumps({"title": "Engineer"}))
        mock_mapping = MagicMock()
        mock_mapping.to_silver.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
            "locations": "Zurich",
        }
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)

        self._process()

        session = self.SessionLocal()
        self.assertIsNone(
            session.query(JobPosting).filter(JobPosting.url == self.POSTING_URL).first()
        )

    def test_successful_mapped_row_writes_no_ingest_event(self):
        self._seed_raw_job(json.dumps({"title": "Engineer"}))
        mock_mapping = MagicMock()
        mock_mapping.to_silver.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
        }
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)

        self._process()

        session = self.SessionLocal()
        self.assertEqual(session.query(IngestEvent).count(), 0)
        self.assertIsNotNone(
            session.query(JobPosting).filter(JobPosting.url == self.POSTING_URL).first()
        )

    def test_html_row_taking_extraction_path_writes_no_ingest_event(self):
        """Proves the JSON refusals stay on the JSON side: an HTML row that
        also fails to reach Silver still records nothing here."""
        self._seed_raw_job("<html></html>", content_type="text/html")
        self.worker.registry.get_extraction_adapter = MagicMock(return_value=None)

        self._process()

        session = self.SessionLocal()
        self.assertEqual(session.query(IngestEvent).count(), 0)

    @patch("scraper.silver_worker.record_ingest_failure")
    def test_recorder_raising_does_not_stop_the_next_message(self, mock_record):
        mock_record.side_effect = Exception("boom")
        self._seed_raw_job(json.dumps({"title": "Engineer"}))
        self.worker.registry.get_detail_mapping = MagicMock(return_value=None)

        # Must not propagate out of process_message, even though the call it
        # makes on this path is mocked to raise.
        self._process()

        other_url = "https://boards.greenhouse.io/acme/jobs/456"
        self._seed_raw_job(
            json.dumps({"title": "Engineer"}),
            url=other_url,
        )
        mock_mapping = MagicMock()
        mock_mapping.to_silver.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
        }
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mock_mapping)

        self._process(url=other_url)

        session = self.SessionLocal()
        self.assertIsNotNone(
            session.query(JobPosting).filter(JobPosting.url == other_url).first()
        )


if __name__ == "__main__":
    unittest.main()
