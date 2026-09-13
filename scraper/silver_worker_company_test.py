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
    Base,
    IngestEvent,
    JobPosting,
    RawJobPosting,
    StartUrl,
)
from scraper.silver_worker import SilverWorker, SilverWorkerConfig


@compiles(JSONB, "sqlite")
@compiles(UUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


class SilverWorkerCompanyTest(unittest.TestCase):
    """A board's stated company overrides whatever a mapping or adapter produced.

    Each case builds its own engine and worker so H5 can drop a table under
    one of them without disturbing any other case.
    """

    SOURCE_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    POSTING_URL = "https://boards.greenhouse.io/acme/jobs/123"

    def _world(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_local = sessionmaker(bind=engine)
        config = SilverWorkerConfig(
            redis_host="localhost",
            redis_port=6379,
            queue_name="test_silver_queue",
            log_level="ERROR",
        )
        worker = SilverWorker(config)
        worker.redis = MagicMock()
        return engine, session_local, worker

    def _seed_start_url(self, session_local, company_name):
        start_url_id = uuid.uuid4()
        session = session_local()
        session.add(
            StartUrl(
                id=start_url_id,
                name=f"Board {start_url_id}",
                url=f"https://{start_url_id}.example.com",
                type="api",
                company_name=company_name,
            )
        )
        session.commit()
        session.close()
        return start_url_id

    def _seed_raw_job(self, session_local, start_url_id, content_type, raw_content):
        session = session_local()
        session.add(
            RawJobPosting(
                url=self.POSTING_URL,
                source_url=self.SOURCE_URL,
                content_type=content_type,
                raw_content=raw_content,
                start_url_id=start_url_id,
            )
        )
        session.commit()
        session.close()

    def _process(self, session_local, worker):
        with (
            patch("scraper.silver_worker.SessionLocal", session_local),
            patch("scraper.ingest_events.SessionLocal", session_local),
        ):
            worker.process_message(json.dumps({"url": self.POSTING_URL}))

    def _job_posting(self, session_local):
        session = session_local()
        job = (
            session.query(JobPosting).filter(JobPosting.url == self.POSTING_URL).first()
        )
        session.close()
        return job

    def _ingest_events(self, session_local):
        session = session_local()
        events = session.query(IngestEvent).all()
        session.close()
        return events

    def _mapping(self, company_name=None, has_key=True):
        mapping = MagicMock()
        data = {"title": "Engineer", "description": "Build things"}
        if has_key:
            data["company_name"] = company_name
        mapping.to_silver.return_value = data
        return mapping

    def test_m1_mapped_row_company_wins_over_mapping_company(self):
        _engine, session_local, worker = self._world()
        start_url_id = self._seed_start_url(session_local, "Acme Corp")
        self._seed_raw_job(session_local, start_url_id, "application/json", "{}")
        worker.registry.get_detail_mapping = MagicMock(
            return_value=self._mapping(company_name="Greenhouse")
        )

        self._process(session_local, worker)

        self.assertEqual(self._job_posting(session_local).company_name, "Acme Corp")

    def test_m2_row_company_used_when_mapping_omits_company_key(self):
        _engine, session_local, worker = self._world()
        start_url_id = self._seed_start_url(session_local, "Acme Corp")
        self._seed_raw_job(session_local, start_url_id, "application/json", "{}")
        worker.registry.get_detail_mapping = MagicMock(
            return_value=self._mapping(has_key=False)
        )

        self._process(session_local, worker)

        self.assertEqual(self._job_posting(session_local).company_name, "Acme Corp")
        self.assertEqual(self._ingest_events(session_local), [])

    def test_m3_no_row_company_falls_back_to_mapping_company(self):
        _engine, session_local, worker = self._world()
        start_url_id = self._seed_start_url(session_local, None)
        self._seed_raw_job(session_local, start_url_id, "application/json", "{}")
        worker.registry.get_detail_mapping = MagicMock(
            return_value=self._mapping(company_name="Beta")
        )

        self._process(session_local, worker)

        self.assertEqual(self._job_posting(session_local).company_name, "Beta")

    def test_m4_null_start_url_id_falls_back_to_mapping_company(self):
        _engine, session_local, worker = self._world()
        self._seed_raw_job(session_local, None, "application/json", "{}")
        worker.registry.get_detail_mapping = MagicMock(
            return_value=self._mapping(company_name="Beta")
        )

        self._process(session_local, worker)

        self.assertEqual(self._job_posting(session_local).company_name, "Beta")

    def test_m5_no_row_company_and_no_mapping_company_is_invalid_shape(self):
        _engine, session_local, worker = self._world()
        start_url_id = self._seed_start_url(session_local, None)
        self._seed_raw_job(session_local, start_url_id, "application/json", "{}")
        worker.registry.get_detail_mapping = MagicMock(
            return_value=self._mapping(has_key=False)
        )

        self._process(session_local, worker)

        self.assertIsNone(self._job_posting(session_local))
        (event,) = self._ingest_events(session_local)
        self.assertEqual(event.reason, INGEST_REASON_INVALID_SHAPE)

    def test_m6_blank_row_company_falls_back_to_mapping_company(self):
        for row_company in ("", "   "):
            with self.subTest(row_company=row_company):
                _engine, session_local, worker = self._world()
                start_url_id = self._seed_start_url(session_local, row_company)
                self._seed_raw_job(
                    session_local, start_url_id, "application/json", "{}"
                )
                worker.registry.get_detail_mapping = MagicMock(
                    return_value=self._mapping(company_name="Beta")
                )

                self._process(session_local, worker)

                self.assertEqual(self._job_posting(session_local).company_name, "Beta")

    def test_m7_row_company_written_unstripped(self):
        _engine, session_local, worker = self._world()
        start_url_id = self._seed_start_url(session_local, " Acme Corp ")
        self._seed_raw_job(session_local, start_url_id, "application/json", "{}")
        worker.registry.get_detail_mapping = MagicMock(
            return_value=self._mapping(company_name="Beta")
        )

        self._process(session_local, worker)

        self.assertEqual(self._job_posting(session_local).company_name, " Acme Corp ")

    def test_h1_html_row_company_wins_over_adapter_company(self):
        _engine, session_local, worker = self._world()
        start_url_id = self._seed_start_url(session_local, "Acme Corp")
        self._seed_raw_job(session_local, start_url_id, "text/html", "<html></html>")
        adapter = MagicMock()
        adapter.extract.return_value = {
            "title": "Engineer",
            "company_name": "Google",
            "description": "Build things",
        }
        worker.registry.get_extraction_adapter = MagicMock(return_value=adapter)

        self._process(session_local, worker)

        self.assertEqual(self._job_posting(session_local).company_name, "Acme Corp")

    def test_h2_row_company_used_when_adapter_omits_company_key(self):
        _engine, session_local, worker = self._world()
        start_url_id = self._seed_start_url(session_local, "Acme Corp")
        self._seed_raw_job(session_local, start_url_id, "text/html", "<html></html>")
        adapter = MagicMock()
        adapter.extract.return_value = {
            "title": "Engineer",
            "description": "Build things",
        }
        worker.registry.get_extraction_adapter = MagicMock(return_value=adapter)
        worker._handle_missing_or_failed_adapter = MagicMock()

        self._process(session_local, worker)

        self.assertEqual(self._job_posting(session_local).company_name, "Acme Corp")
        worker._handle_missing_or_failed_adapter.assert_not_called()

    def test_h3_no_row_company_falls_back_to_adapter_company(self):
        _engine, session_local, worker = self._world()
        start_url_id = self._seed_start_url(session_local, None)
        self._seed_raw_job(session_local, start_url_id, "text/html", "<html></html>")
        adapter = MagicMock()
        adapter.extract.return_value = {
            "title": "Engineer",
            "company_name": "Google",
            "description": "Build things",
        }
        worker.registry.get_extraction_adapter = MagicMock(return_value=adapter)

        self._process(session_local, worker)

        self.assertEqual(self._job_posting(session_local).company_name, "Google")

    def test_h4_empty_extraction_still_fails_despite_row_company(self):
        _engine, session_local, worker = self._world()
        start_url_id = self._seed_start_url(session_local, "Acme Corp")
        self._seed_raw_job(session_local, start_url_id, "text/html", "<html></html>")
        adapter = MagicMock()
        adapter.extract.return_value = {}
        worker.registry.get_extraction_adapter = MagicMock(return_value=adapter)
        worker._handle_missing_or_failed_adapter = MagicMock()

        self._process(session_local, worker)

        self.assertIsNone(self._job_posting(session_local))
        worker._handle_missing_or_failed_adapter.assert_called_once()

    def test_h5_failed_company_lookup_skips_adapter_failure_handler(self):
        engine, session_local, worker = self._world()
        start_url_id = self._seed_start_url(session_local, "Acme Corp")
        self._seed_raw_job(session_local, start_url_id, "text/html", "<html></html>")
        adapter = MagicMock()
        adapter.extract.return_value = {
            "title": "Engineer",
            "company_name": "Google",
            "description": "Build things",
        }
        worker.registry.get_extraction_adapter = MagicMock(return_value=adapter)
        worker._handle_missing_or_failed_adapter = MagicMock()
        StartUrl.__table__.drop(engine)

        self._process(session_local, worker)

        self.assertIsNone(self._job_posting(session_local))
        worker._handle_missing_or_failed_adapter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
