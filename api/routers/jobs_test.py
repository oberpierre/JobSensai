import unittest
import uuid
from datetime import datetime, timedelta

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


class JobsRouterTestCase(unittest.TestCase):
    """Wires an app and a TestClient against an isolated SQLite database.

    Leaves the database empty, since a subclass seeds whatever fixture its
    own tests need.
    """

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

    def _seed(self, *jobs: JobPosting) -> None:
        session = self.session_factory()
        session.add_all(jobs)
        session.commit()
        session.close()


class TestListJobs(JobsRouterTestCase):
    def setUp(self):
        super().setUp()
        self._seed(
            _job(
                url="https://example.com/1",
                title="Backend Engineer",
                company_name="Acme",
                description="# Role\n\n" + ("x" * 300),
                metadata_={"salary": "n/a"},
                created_at=datetime(2026, 1, 1),
            ),
            _job(
                url="https://example.com/2",
                title="Closed Role",
                company_name="Acme",
                description="short",
                created_at=datetime(2025, 1, 1),
                deleted_at=datetime(2025, 6, 1),
            ),
        )

    def test_default_excludes_closed(self):
        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)

    def test_include_closed_true_includes_it(self):
        response = self.client.get("/api/jobs", params={"include_closed": "true"})
        self.assertEqual(response.json()["total"], 2)

    def test_q_filters_by_title_or_company(self):
        response = self.client.get("/api/jobs", params={"q": "backend"})
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["title"], "Backend Engineer")

    def test_snippet_is_first_240_chars_markdown_stripped(self):
        response = self.client.get("/api/jobs")
        snippet = response.json()["items"][0]["snippet"]
        self.assertNotIn("#", snippet)
        self.assertLessEqual(len(snippet), 240)

    def test_snippet_keeps_an_underscore_inside_a_word(self):
        self._seed(
            _job(
                url="https://example.com/3",
                title="Platform Engineer",
                description="Vendors node_modules, cleaned on every build.",
            )
        )
        response = self.client.get("/api/jobs", params={"q": "platform"})
        snippet = response.json()["items"][0]["snippet"]
        self.assertIn("node_modules", snippet)

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


class TestWildcardEscaping(JobsRouterTestCase):
    def setUp(self):
        super().setUp()
        self._seed(
            _job(url="https://example.com/1", title="Team C_O Coordinator"),
            _job(url="https://example.com/2", title="Team CEO Coordinator"),
        )

    def test_underscore_in_q_is_literal_not_a_wildcard(self):
        response = self.client.get("/api/jobs", params={"q": "c_o"})
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["title"], "Team C_O Coordinator")


class TestOrderingAndPaging(JobsRouterTestCase):
    def setUp(self):
        super().setUp()
        base = datetime(2026, 1, 1)
        self._seed(
            *[
                _job(
                    url=f"https://example.com/{i}",
                    title=f"Job {i:02d}",
                    created_at=base + timedelta(days=i),
                )
                for i in range(30)
            ]
        )

    def test_page_one_is_the_thirty_newest_first(self):
        response = self.client.get("/api/jobs")
        titles = [item["title"] for item in response.json()["items"]]
        self.assertEqual(titles[0], "Job 29")
        self.assertEqual(len(titles), 25)

    def test_page_two_holds_the_remaining_five(self):
        response = self.client.get("/api/jobs", params={"page": 2})
        body = response.json()
        titles = [item["title"] for item in body["items"]]
        self.assertEqual(
            titles,
            ["Job 04", "Job 03", "Job 02", "Job 01", "Job 00"],
        )
        self.assertEqual(body["total"], 30)


class TestCompanyCount(JobsRouterTestCase):
    def setUp(self):
        super().setUp()
        self._seed(
            _job(url="https://example.com/a1", title="A1", company_name="Acme"),
            _job(url="https://example.com/a2", title="A2", company_name="Acme"),
            _job(url="https://example.com/a3", title="A3", company_name="Acme"),
            _job(url="https://example.com/b1", title="B1", company_name="Globex"),
            _job(url="https://example.com/b2", title="B2", company_name="Globex"),
        )

    def test_company_count_is_the_distinct_company_count_not_the_item_count(self):
        response = self.client.get("/api/jobs")
        body = response.json()
        self.assertEqual(len(body["items"]), 5)
        self.assertEqual(body["company_count"], 2)


class TestIncludeClosedOnAPairThatDiffersOnlyInDeletedAt(JobsRouterTestCase):
    def setUp(self):
        super().setUp()
        self._seed(
            _job(
                url="https://example.com/open",
                title="Support Engineer",
                deleted_at=None,
            ),
            _job(
                url="https://example.com/closed",
                title="Support Engineer",
                deleted_at=datetime(2026, 1, 2),
            ),
        )

    def test_include_closed_false_returns_the_open_row_only(self):
        response = self.client.get("/api/jobs")
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertFalse(body["items"][0]["closed"])

    def test_include_closed_true_returns_both_rows(self):
        response = self.client.get("/api/jobs", params={"include_closed": "true"})
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual({item["closed"] for item in body["items"]}, {False, True})


class TestSort(JobsRouterTestCase):
    def setUp(self):
        super().setUp()
        self._seed(
            _job(
                url="https://example.com/1",
                title="Oldest",
                created_at=datetime(2026, 1, 1),
            ),
            _job(
                url="https://example.com/2",
                title="Newest",
                created_at=datetime(2026, 1, 30),
            ),
        )

    def test_default_sort_is_newest_first(self):
        response = self.client.get("/api/jobs")
        titles = [item["title"] for item in response.json()["items"]]
        self.assertEqual(titles, ["Newest", "Oldest"])

    def test_sort_oldest_reverses_the_order(self):
        response = self.client.get("/api/jobs", params={"sort": "oldest"})
        titles = [item["title"] for item in response.json()["items"]]
        self.assertEqual(titles, ["Oldest", "Newest"])


class TestFacetParameters(JobsRouterTestCase):
    def setUp(self):
        super().setUp()
        self._seed(
            _job(
                url="https://example.com/1",
                title="Backend Engineer",
                company_name="Acme",
                employment_type="full_time",
                locations=["Zurich"],
            ),
            _job(
                url="https://example.com/2",
                title="Frontend Engineer",
                company_name="Globex",
                employment_type="contract",
                locations=["Singapore"],
            ),
            _job(
                url="https://example.com/3",
                title="Data Scientist",
                company_name="Acme",
                employment_type=None,
                locations=["Zurich", "Singapore"],
            ),
        )

    def test_location_is_or_within_the_facet(self):
        response = self.client.get(
            "/api/jobs", params={"location": ["Zurich", "Singapore"]}
        )
        self.assertEqual(response.json()["total"], 3)

    def test_company_narrows_to_the_selected_companies(self):
        response = self.client.get("/api/jobs", params={"company": "Globex"})
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["title"], "Frontend Engineer")

    def test_employment_type_unspecified_matches_null(self):
        response = self.client.get(
            "/api/jobs", params={"employment_type": "__unspecified__"}
        )
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["title"], "Data Scientist")

    def test_facets_combine_and_across_or_within(self):
        response = self.client.get(
            "/api/jobs",
            params={
                "location": "Zurich",
                "company": "Acme",
                "employment_type": ["full_time", "__unspecified__"],
            },
        )
        titles = {item["title"] for item in response.json()["items"]}
        self.assertEqual(titles, {"Backend Engineer", "Data Scientist"})


class TestJobFacets(JobsRouterTestCase):
    def setUp(self):
        super().setUp()
        self._seed(
            _job(
                url="https://example.com/1",
                title="Backend Engineer",
                company_name="Acme",
                locations=["Zurich"],
            ),
            _job(
                url="https://example.com/2",
                title="Backend Lead",
                company_name="Acme",
                locations=["Zurich", "Singapore"],
            ),
            _job(
                url="https://example.com/3",
                title="Frontend Engineer",
                company_name="Globex",
                locations=["Singapore"],
            ),
        )

    def test_facets_report_value_and_count(self):
        response = self.client.get("/api/jobs/facets")
        body = response.json()
        self.assertIn({"value": "Acme", "count": 2}, body["company"])
        self.assertIn({"value": "Globex", "count": 1}, body["company"])

    def test_other_facets_narrow_a_facets_counts_and_its_own_selection_does_not(self):
        # Two of the three postings are Acme's, one of those in Singapore
        # alongside Zurich, so selecting company=Acme drops Singapore's count
        # from 2 to 1 while selecting location=Zurich leaves location untouched.
        bare = self.client.get("/api/jobs/facets").json()
        by_company = self.client.get(
            "/api/jobs/facets", params={"company": "Acme"}
        ).json()
        by_location = self.client.get(
            "/api/jobs/facets", params={"location": "Zurich"}
        ).json()
        by_both = self.client.get(
            "/api/jobs/facets", params={"company": "Acme", "location": "Zurich"}
        ).json()

        self.assertEqual(
            {f["value"]: f["count"] for f in bare["location"]},
            {"Zurich": 2, "Singapore": 2},
        )
        self.assertEqual(
            {f["value"]: f["count"] for f in by_company["location"]},
            {"Zurich": 2, "Singapore": 1},
        )
        self.assertEqual(by_location["location"], bare["location"])
        self.assertEqual(by_both["location"], by_company["location"])


if __name__ == "__main__":
    unittest.main()
