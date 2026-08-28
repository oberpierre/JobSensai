import unittest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import create_app
from scraper.database import get_db
from scraper.models import Base, JobPosting


@compiles(JSONB, "sqlite")
@compiles(PgUUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


class JobsRouterTestCase(unittest.TestCase):
    def setUp(self):
        # FastAPI runs sync route handlers on a worker thread, and SQLite's :memory:
        # database is otherwise per-connection: a StaticPool keeps every thread on
        # the one connection the tables were created on.
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine)

        self.app = create_app()

        def _override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(self.app)

        seed_session = self.session_factory()
        seed_session.add_all(
            [
                JobPosting(
                    id=uuid.uuid4(),
                    url="https://example.com/1",
                    title="Backend Engineer",
                    company_name="Acme",
                    employment_type="full_time",
                    locations=["Zurich"],
                    categories=[],
                    description="# Role\n\n" + ("x" * 300),
                    metadata_={"salary": "n/a"},
                    created_at=datetime(2026, 1, 1),
                ),
                JobPosting(
                    id=uuid.uuid4(),
                    url="https://example.com/2",
                    title="Closed Role",
                    company_name="Acme",
                    employment_type="full_time",
                    locations=["Zurich"],
                    categories=[],
                    description="short",
                    metadata_={},
                    created_at=datetime(2025, 1, 1),
                    deleted_at=datetime(2025, 6, 1),
                ),
            ]
        )
        seed_session.commit()
        seed_session.close()


class TestListJobs(JobsRouterTestCase):
    def test_default_excludes_closed(self):
        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["company_count"], 1)

    def test_include_closed_true_includes_it(self):
        response = self.client.get("/api/jobs", params={"include_closed": "true"})
        self.assertEqual(response.json()["total"], 2)

    def test_q_filters_by_title_or_company(self):
        response = self.client.get("/api/jobs", params={"q": "backend"})
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["title"], "Backend Engineer")

    def test_page_two_is_empty_past_the_seeded_rows(self):
        response = self.client.get("/api/jobs", params={"page": 2})
        self.assertEqual(response.json()["items"], [])

    def test_snippet_is_first_240_chars_markdown_stripped(self):
        response = self.client.get("/api/jobs")
        snippet = response.json()["items"][0]["snippet"]
        self.assertNotIn("#", snippet)
        self.assertLessEqual(len(snippet), 240)

    def test_timestamps_carry_an_explicit_utc_offset(self):
        response = self.client.get("/api/jobs")
        first_seen = response.json()["items"][0]["first_seen"]
        self.assertTrue(first_seen.endswith("+00:00") or first_seen.endswith("Z"))

    def test_closed_posting_is_marked(self):
        response = self.client.get("/api/jobs", params={"include_closed": "true"})
        closed = next(
            item for item in response.json()["items"] if item["title"] == "Closed Role"
        )
        self.assertTrue(closed["closed"])


if __name__ == "__main__":
    unittest.main()
