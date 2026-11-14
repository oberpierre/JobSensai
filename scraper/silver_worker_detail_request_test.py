import json
import logging
import unittest
import uuid
from datetime import datetime
from unittest.mock import MagicMock, call, patch

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from scraper.models import (
    INGEST_REASON_NO_RULE,
    INGEST_REASON_UNPARSEABLE_CONTENT,
    INGEST_STAGE_DETAIL,
    Base,
    IngestEvent,
    JobPosting,
    RawJobPosting,
)
from scraper.silver_worker import SilverWorker, SilverWorkerConfig

SOURCE_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
HOSTNAME = "boards-api.greenhouse.io"
KEY = "LEARNING_REQUESTED:detail:boards-api.greenhouse.io"
POSTING_URLS = (
    "https://boards.greenhouse.io/acme/jobs/123",
    "https://boards.greenhouse.io/acme/jobs/456",
    "https://boards.greenhouse.io/acme/jobs/789",
)


# sqlite has no JSONB/UUID types, and Base.metadata.create_all() would fail
# against it otherwise. Rendering them as TEXT is safe because only row
# persistence is under test here, not the columns' real types.
@compiles(JSONB, "sqlite")
@compiles(UUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


class TestDetailMappingRequest(unittest.TestCase):
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

        self.worker = SilverWorker(
            SilverWorkerConfig(
                redis_host="localhost",
                redis_port=6379,
                queue_name="test_silver_queue",
                log_level="ERROR",
            )
        )
        self.store: dict[str, str] = {}
        self.worker.redis = MagicMock()
        self.worker.redis.set.side_effect = self._set
        self.worker.redis.delete.side_effect = lambda key: self.store.pop(key, None)
        self.worker.registry.get_detail_mapping = MagicMock(return_value=None)
        self.start_url_id = uuid.uuid4()

    def _set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def _seed(self, url, raw_content='{"title": "Engineer"}', source_url=SOURCE_URL):
        session = self.SessionLocal()
        session.add(
            RawJobPosting(
                url=url,
                source_url=source_url,
                content_type="application/json",
                raw_content=raw_content,
                start_url_id=self.start_url_id,
            )
        )
        session.commit()
        session.close()

    def _process(self, url):
        self.worker.process_message(json.dumps({"url": url}))

    def _events(self):
        session = self.SessionLocal()
        try:
            return session.query(IngestEvent).all()
        finally:
            session.close()

    def _payload(self):
        return json.loads(self.worker.redis.lpush.call_args.args[1])

    def _errors(self, logs):
        return [r for r in logs.records if r.levelno >= logging.ERROR]

    def test_many_postings_of_one_host_enqueue_one_task(self):
        for url in POSTING_URLS:
            self._seed(url)
        for url in POSTING_URLS:
            self._process(url)

        self.worker.redis.lpush.assert_called_once()
        self.assertEqual(
            self.worker.redis.lpush.call_args.args[0], "extraction_learning_tasks"
        )
        self.assertEqual(
            self.worker.redis.set.call_args_list,
            [call(KEY, "1", nx=True, ex=1800)] * 3,
        )
        events = self._events()
        self.assertEqual(len(events), 3)
        for event in events:
            self.assertEqual(event.reason, INGEST_REASON_NO_RULE)
            self.assertEqual(event.stage, INGEST_STAGE_DETAIL)

    def test_task_payload_is_the_mapping_form_with_the_row_verbatim(self):
        raw = '{"title":  "Ingénieur"}'
        self._seed(POSTING_URLS[0], raw_content=raw)
        self._process(POSTING_URLS[0])

        payload = self._payload()
        self.assertEqual(
            set(payload), {"artifact", "domain", "url", "body", "timestamp"}
        )
        self.assertEqual(payload["artifact"], "mapping")
        self.assertEqual(payload["domain"], HOSTNAME)
        self.assertEqual(payload["url"], SOURCE_URL)
        self.assertEqual(payload["body"], raw)
        self.assertIsNotNone(datetime.fromisoformat(payload["timestamp"]).tzinfo)

    def test_domain_is_the_hostname_of_source_url(self):
        source = "https://Boards-API.Greenhouse.io:443/v1/boards/acme/jobs"
        self._seed(POSTING_URLS[0], source_url=source)
        self._process(POSTING_URLS[0])

        payload = self._payload()
        self.assertEqual(payload["domain"], "boards-api.greenhouse.io")
        self.assertEqual(self.worker.redis.set.call_args.args[0], KEY)
        self.assertEqual(payload["url"], source)

    def test_no_rule_line_logs_at_warning_and_nothing_at_error(self):
        self._seed(POSTING_URLS[0])
        with self.assertLogs("scraper.silver_worker", level="DEBUG") as logs:
            self._process(POSTING_URLS[0])

        (record,) = [r for r in logs.records if "No detail mapping" in r.getMessage()]
        self.assertEqual(record.levelno, logging.WARNING)
        self.assertIn(HOSTNAME, record.getMessage())
        self.assertIn(POSTING_URLS[0], record.getMessage())
        self.assertEqual(self._errors(logs), [])

    def test_failed_push_releases_the_key_for_the_next_posting(self):
        self.worker.redis.lpush.side_effect = [RuntimeError("boom"), 1]
        for url in POSTING_URLS[:2]:
            self._seed(url)
        for url in POSTING_URLS[:2]:
            self._process(url)

        self.assertEqual(self.worker.redis.lpush.call_count, 2)
        self.worker.redis.delete.assert_called_once_with(KEY)
        events = self._events()
        self.assertEqual([e.reason for e in events], [INGEST_REASON_NO_RULE] * 2)

    def test_no_redis_client_logs_error_and_returns(self):
        self.worker.redis = None
        with self.assertLogs("scraper.silver_worker", level="DEBUG") as logs:
            result = self.worker._request_detail_mapping(SOURCE_URL, HOSTNAME, "{}")

        self.assertIsNone(result)
        (record,) = self._errors(logs)
        self.assertIn(HOSTNAME, record.getMessage())
        self.assertNotIn("NoneType", record.getMessage())

    def test_set_raising_logs_error_and_deletes_nothing(self):
        self.worker.redis.set.side_effect = RuntimeError("down")
        with self.assertLogs("scraper.silver_worker", level="DEBUG") as logs:
            self.worker._request_detail_mapping(SOURCE_URL, HOSTNAME, "{}")

        self.worker.redis.lpush.assert_not_called()
        self.worker.redis.delete.assert_not_called()
        (record,) = self._errors(logs)
        self.assertIn(HOSTNAME, record.getMessage())

    def test_push_raising_deletes_the_key_and_logs_error(self):
        self.worker.redis.lpush.side_effect = RuntimeError("boom")
        with self.assertLogs("scraper.silver_worker", level="DEBUG") as logs:
            self.worker._request_detail_mapping(SOURCE_URL, HOSTNAME, "{}")

        self.worker.redis.delete.assert_called_once_with(KEY)
        (record,) = self._errors(logs)
        self.assertIn(HOSTNAME, record.getMessage())

    def test_delete_raising_after_a_failed_push_still_returns(self):
        self.worker.redis.lpush.side_effect = RuntimeError("boom")
        self.worker.redis.delete.side_effect = RuntimeError("gone")
        with self.assertLogs("scraper.silver_worker", level="DEBUG") as logs:
            self.worker._request_detail_mapping(SOURCE_URL, HOSTNAME, "{}")

        errors = self._errors(logs)
        self.assertEqual(len(errors), 2)
        for record in errors:
            self.assertIn(HOSTNAME, record.getMessage())

    def test_source_url_without_hostname_requests_nothing(self):
        with self.assertLogs("scraper.silver_worker", level="DEBUG") as logs:
            self.worker._request_detail_mapping("not-a-url", None, "{}")

        self.worker.redis.set.assert_not_called()
        self.worker.redis.lpush.assert_not_called()
        (record,) = self._errors(logs)
        self.assertIn("not-a-url", record.getMessage())

    def _assert_unparseable_requests_nothing(self, raw_content):
        self._seed(POSTING_URLS[0], raw_content=raw_content)
        self._process(POSTING_URLS[0])

        (event,) = self._events()
        self.assertEqual(event.reason, INGEST_REASON_UNPARSEABLE_CONTENT)
        self.worker.registry.get_detail_mapping.assert_not_called()
        self.worker.redis.set.assert_not_called()
        self.worker.redis.lpush.assert_not_called()

    def test_unparseable_body_without_mapping_records_unparseable_and_requests_nothing(
        self,
    ):
        self._assert_unparseable_requests_nothing("not json at all")

    def test_scalar_body_without_mapping_records_unparseable_and_requests_nothing(
        self,
    ):
        self._assert_unparseable_requests_nothing("3")

    def test_host_with_a_mapping_requests_nothing(self):
        mapping = MagicMock()
        mapping.to_silver.return_value = {
            "title": "Engineer",
            "company_name": "Acme",
            "description": "Build things",
        }
        self.worker.registry.get_detail_mapping = MagicMock(return_value=mapping)
        self._seed(POSTING_URLS[0])
        self._process(POSTING_URLS[0])

        session = self.SessionLocal()
        self.assertIsNotNone(
            session.query(JobPosting).filter(JobPosting.url == POSTING_URLS[0]).first()
        )
        session.close()
        self.worker.redis.set.assert_not_called()
        self.worker.redis.lpush.assert_not_called()

    def test_no_redis_client_still_records_no_rule(self):
        self.worker.redis = None
        self._seed(POSTING_URLS[0])
        self._process(POSTING_URLS[0])

        (event,) = self._events()
        self.assertEqual(event.reason, INGEST_REASON_NO_RULE)


if __name__ == "__main__":
    unittest.main()
