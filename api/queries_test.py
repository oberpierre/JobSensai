import unittest
import uuid
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from api.queries import filtered_job_postings
from scraper.models import Base, JobPosting


# sqlite has no JSONB/UUID types, and Base.metadata.create_all() would fail
# against it otherwise. Rendering them as TEXT is safe here because the
# mapping under test is our own column assignment, not either type's DDL.
@compiles(JSONB, "sqlite")
@compiles(PgUUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


def _job(**overrides) -> JobPosting:
    defaults = {
        "id": uuid.uuid4(),
        "url": f"https://example.com/{uuid.uuid4()}",
        "title": "Backend Engineer",
        "company_name": "Acme",
        "employment_type": "full_time",
        "locations": ["Zurich"],
        "categories": [],
        "description": "A job.",
        "metadata_": {},
        "created_at": datetime(2026, 1, 1),
        "deleted_at": None,
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


class TestFilteredJobPostings(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()
        self.addCleanup(self.session.close)
        self.session.add_all(
            [
                _job(title="Backend Engineer", company_name="Acme"),
                _job(title="Frontend Engineer", company_name="Globex"),
                _job(
                    title="Closed Backend Role",
                    company_name="Acme",
                    deleted_at=datetime(2026, 1, 2),
                ),
            ]
        )
        self.session.commit()

    def test_q_matches_title_case_insensitively(self):
        jobs = filtered_job_postings(self.session, q="BACKEND", include_closed=False)
        self.assertEqual({j.title for j in jobs}, {"Backend Engineer"})

    def test_q_matches_company_name(self):
        jobs = filtered_job_postings(self.session, q="globex", include_closed=False)
        self.assertEqual({j.title for j in jobs}, {"Frontend Engineer"})

    def test_include_closed_false_excludes_deleted(self):
        jobs = filtered_job_postings(self.session, q=None, include_closed=False)
        self.assertNotIn("Closed Backend Role", {j.title for j in jobs})

    def test_include_closed_true_includes_deleted(self):
        jobs = filtered_job_postings(self.session, q=None, include_closed=True)
        self.assertIn("Closed Backend Role", {j.title for j in jobs})

    def test_no_q_returns_every_open_posting(self):
        jobs = filtered_job_postings(self.session, q=None, include_closed=False)
        self.assertEqual(len(jobs), 2)


if __name__ == "__main__":
    unittest.main()
