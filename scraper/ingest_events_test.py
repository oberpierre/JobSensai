import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from scraper.ingest_events import record_ingest_failure
from scraper.models import Base, IngestEvent


# sqlite has no JSONB/UUID types, and Base.metadata.create_all() would fail
# against it otherwise. Rendering them as TEXT is safe because only row
# persistence is under test here, not the columns' real types.
@compiles(JSONB, "sqlite")
@compiles(UUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


class TestRecordIngestFailure(unittest.TestCase):
    SOURCE_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    POSTING_URL = "https://boards.greenhouse.io/acme/jobs/123"

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        patcher = patch("scraper.ingest_events.SessionLocal", self.SessionLocal)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _rows(self):
        return self.SessionLocal().query(IngestEvent).all()

    def test_writes_a_complete_row(self):
        start_url_id = uuid.uuid4()

        record_ingest_failure(
            stage="detail",
            reason="no_rule",
            source_url=self.SOURCE_URL,
            posting_url=self.POSTING_URL,
            start_url_id=start_url_id,
            detail="boom",
        )

        (row,) = self._rows()
        self.assertEqual(row.stage, "detail")
        self.assertEqual(row.reason, "no_rule")
        self.assertEqual(row.source_url, self.SOURCE_URL)
        self.assertEqual(row.posting_url, self.POSTING_URL)
        self.assertEqual(row.start_url_id, start_url_id)
        self.assertEqual(row.detail, "boom")
        self.assertEqual(row.domain, "boards-api.greenhouse.io")

    def test_optional_fields_may_be_omitted(self):
        record_ingest_failure(
            stage="detail",
            reason="no_rule",
            source_url=self.SOURCE_URL,
        )

        (row,) = self._rows()
        self.assertIsNone(row.posting_url)
        self.assertIsNone(row.start_url_id)
        self.assertIsNone(row.detail)

    def test_detail_longer_than_max_is_truncated(self):
        long_detail = "x" * 600

        record_ingest_failure(
            stage="detail",
            reason="rule_raised",
            source_url=self.SOURCE_URL,
            detail=long_detail,
        )

        (row,) = self._rows()
        self.assertEqual(len(row.detail), 500)
        self.assertEqual(row.detail, "x" * 500)

    def test_url_urlsplit_cannot_parse_writes_no_row_and_returns_normally(self):
        with self.assertLogs("scraper.ingest_events", level="ERROR") as captured:
            record_ingest_failure(
                stage="detail",
                reason="no_rule",
                source_url="http://[::1",
            )

        self.assertEqual(self._rows(), [])
        self.assertTrue(any("http://[::1" in message for message in captured.output))

    def test_url_with_no_authority_component_stores_unknown_domain(self):
        record_ingest_failure(
            stage="detail",
            reason="unparseable_content",
            source_url="/just/a/path",
            posting_url=self.POSTING_URL,
        )

        (row,) = self._rows()
        self.assertEqual(row.domain, "(unknown)")
        self.assertEqual(row.source_url, "/just/a/path")
        self.assertEqual(row.posting_url, self.POSTING_URL)


if __name__ == "__main__":
    unittest.main()
