import unittest
import uuid
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from api.queries import paged_job_postings
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


class QueriesTestCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()
        self.addCleanup(self.session.close)

    def _page(self, **kwargs):
        kwargs.setdefault("q", None)
        kwargs.setdefault("include_closed", False)
        kwargs.setdefault("page", 1)
        kwargs.setdefault("page_size", 25)
        return paged_job_postings(self.session, **kwargs)


class TestFiltering(QueriesTestCase):
    def setUp(self):
        super().setUp()
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
        page = self._page(q="BACKEND")
        self.assertEqual({j.title for j in page.items}, {"Backend Engineer"})

    def test_q_matches_company_name(self):
        page = self._page(q="globex")
        self.assertEqual({j.title for j in page.items}, {"Frontend Engineer"})

    def test_include_closed_false_excludes_deleted(self):
        page = self._page()
        self.assertNotIn("Closed Backend Role", {j.title for j in page.items})

    def test_include_closed_true_includes_deleted(self):
        page = self._page(include_closed=True)
        self.assertIn("Closed Backend Role", {j.title for j in page.items})

    def test_no_q_returns_every_open_posting(self):
        page = self._page()
        self.assertEqual(page.total, 2)


class TestWildcardEscaping(QueriesTestCase):
    def setUp(self):
        super().setUp()
        self.session.add_all(
            [
                _job(title="Team C_O Coordinator", company_name="Acme"),
                _job(title="Team CEO Coordinator", company_name="Acme"),
                _job(title="AC%ME Corp", company_name="Widgets"),
                _job(title="AC000ME Corp", company_name="Widgets"),
            ]
        )
        self.session.commit()

    def test_underscore_is_literal_not_a_single_character_wildcard(self):
        page = self._page(q="c_o")
        self.assertEqual({j.title for j in page.items}, {"Team C_O Coordinator"})

    def test_percent_is_literal_not_an_any_characters_wildcard(self):
        page = self._page(q="ac%me")
        self.assertEqual({j.title for j in page.items}, {"AC%ME Corp"})


class TestOrdering(QueriesTestCase):
    def test_newest_first_by_created_at(self):
        self.session.add_all(
            [
                _job(title="Middle", created_at=datetime(2026, 1, 15)),
                _job(title="Oldest", created_at=datetime(2026, 1, 1)),
                _job(title="Newest", created_at=datetime(2026, 1, 30)),
            ]
        )
        self.session.commit()
        page = self._page()
        self.assertEqual([j.title for j in page.items], ["Newest", "Middle", "Oldest"])

    def test_id_breaks_a_tie_on_a_shared_created_at(self):
        shared = datetime(2026, 1, 1)
        self.session.add_all(
            [
                _job(title="Low id", created_at=shared, id=uuid.UUID(int=1)),
                _job(title="High id", created_at=shared, id=uuid.UUID(int=2)),
            ]
        )
        self.session.commit()
        page = self._page()
        self.assertEqual([j.title for j in page.items], ["High id", "Low id"])


class TestPaging(QueriesTestCase):
    def setUp(self):
        super().setUp()
        base = datetime(2026, 1, 1)
        self.session.add_all(
            [
                _job(title=f"Job {i:02d}", created_at=base + timedelta(days=i))
                for i in range(5)
            ]
        )
        self.session.commit()

    def test_second_page_holds_the_remaining_rows_newest_first(self):
        # Newest-first order is Job 04, 03, 02, 01, 00, so page_size 2 makes
        # page two [02, 01].
        page = self._page(page=2, page_size=2)
        self.assertEqual([j.title for j in page.items], ["Job 02", "Job 01"])

    def test_total_counts_the_whole_filtered_set_not_one_page(self):
        page = self._page(page=1, page_size=2)
        self.assertEqual(page.total, 5)
        self.assertEqual(len(page.items), 2)


class TestCompanyCount(QueriesTestCase):
    def test_counts_distinct_companies_not_postings(self):
        self.session.add_all(
            [
                _job(title="A1", company_name="Acme"),
                _job(title="A2", company_name="Acme"),
                _job(title="A3", company_name="Acme"),
                _job(title="B1", company_name="Globex"),
                _job(title="B2", company_name="Globex"),
            ]
        )
        self.session.commit()
        page = self._page()
        self.assertEqual(len(page.items), 5)
        self.assertEqual(page.company_count, 2)


class TestIncludeClosedOnAPairThatDiffersOnlyInDeletedAt(QueriesTestCase):
    def setUp(self):
        super().setUp()
        self.open_id = uuid.uuid4()
        self.closed_id = uuid.uuid4()
        self.session.add_all(
            [
                _job(id=self.open_id, title="Support Engineer", deleted_at=None),
                _job(
                    id=self.closed_id,
                    title="Support Engineer",
                    deleted_at=datetime(2026, 1, 2),
                ),
            ]
        )
        self.session.commit()

    def test_include_closed_false_returns_the_open_row_only(self):
        page = self._page(include_closed=False)
        self.assertEqual({j.id for j in page.items}, {self.open_id})

    def test_include_closed_true_returns_both_rows(self):
        page = self._page(include_closed=True)
        self.assertEqual({j.id for j in page.items}, {self.open_id, self.closed_id})


if __name__ == "__main__":
    unittest.main()
