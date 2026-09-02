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
from scraper.models import Base, JobPosting, RawJobPosting, StartUrl


@compiles(JSONB, "sqlite")
@compiles(PgUUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


class BoardsRouterTestCase(unittest.TestCase):
    """Wires an app and a TestClient against an isolated SQLite database."""

    def setUp(self):
        # FastAPI runs sync route handlers on a worker thread, and SQLite's
        # :memory: database is otherwise per-connection: a StaticPool keeps every
        # thread on the one connection the tables were created on.
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

    def _seed(self, *rows) -> None:
        session = self.session_factory()
        session.add_all(rows)
        session.commit()
        session.close()

    def _create(self, name="Example", url="https://example.com", type_="html_crawl"):
        response = self.client.post(
            "/api/boards", json={"name": name, "url": url, "type": type_}
        )
        return response.json()["id"]


class TestListBoards(BoardsRouterTestCase):
    def test_ordered_by_name(self):
        self._seed(
            StartUrl(
                id=uuid.uuid4(),
                name="Zebra",
                url="https://z.example.com",
                type="html_crawl",
            ),
            StartUrl(
                id=uuid.uuid4(),
                name="Alpha",
                url="https://a.example.com",
                type="html_crawl",
            ),
        )

        response = self.client.get("/api/boards")
        self.assertEqual(response.status_code, 200)
        names = [b["name"] for b in response.json()["items"]]
        self.assertEqual(names, ["Alpha", "Zebra"])

    def test_a_board_with_no_bronze_rows_has_a_null_posting_count(self):
        self._seed(
            StartUrl(
                id=uuid.uuid4(),
                name="Alpha",
                url="https://a.example.com",
                type="html_crawl",
            )
        )

        response = self.client.get("/api/boards")
        self.assertIsNone(response.json()["items"][0]["posting_count"])

    def test_a_board_with_raw_rows_but_no_live_postings_has_a_zero_count(self):
        board_id = uuid.uuid4()
        self._seed(
            StartUrl(
                id=board_id,
                name="Alpha",
                url="https://a.example.com",
                type="html_crawl",
            ),
            RawJobPosting(
                id=uuid.uuid4(),
                url="https://a.example.com/job",
                html_content="<html></html>",
                start_url_id=board_id,
            ),
        )

        response = self.client.get("/api/boards")
        self.assertEqual(response.json()["items"][0]["posting_count"], 0)

    def test_a_board_with_attributed_postings_has_the_joined_count(self):
        board_id = uuid.uuid4()
        self._seed(
            StartUrl(
                id=board_id,
                name="Alpha",
                url="https://a.example.com",
                type="html_crawl",
            ),
            RawJobPosting(
                id=uuid.uuid4(),
                url="https://a.example.com/job",
                html_content="<html></html>",
                start_url_id=board_id,
            ),
            JobPosting(
                id=uuid.uuid4(),
                url="https://a.example.com/job",
                title="Engineer",
                company_name="Acme",
                employment_type=None,
                locations=[],
                categories=[],
                description="",
                metadata_={},
                created_at=datetime(2026, 1, 1),
                deleted_at=None,
            ),
        )

        response = self.client.get("/api/boards")
        self.assertEqual(response.json()["items"][0]["posting_count"], 1)


class TestCreateBoard(BoardsRouterTestCase):
    def test_blank_name_is_422(self):
        response = self.client.post(
            "/api/boards",
            json={"name": "  ", "url": "https://example.com", "type": "html_crawl"},
        )
        self.assertEqual(response.status_code, 422)

    def test_duplicate_name_is_409(self):
        payload = {
            "name": "Example",
            "url": "https://example.com",
            "type": "html_crawl",
        }
        first = self.client.post("/api/boards", json=payload)
        self.assertEqual(first.status_code, 201)

        second = self.client.post(
            "/api/boards", json={**payload, "url": "https://example.com/other"}
        )
        self.assertEqual(second.status_code, 409)

    def test_duplicate_url_is_409(self):
        payload = {
            "name": "Example",
            "url": "https://example.com",
            "type": "html_crawl",
        }
        first = self.client.post("/api/boards", json=payload)
        self.assertEqual(first.status_code, 201)

        second = self.client.post("/api/boards", json={**payload, "name": "Other name"})
        self.assertEqual(second.status_code, 409)

    def test_created_board_has_a_null_posting_count_and_health(self):
        response = self.client.post(
            "/api/boards",
            json={
                "name": "Example",
                "url": "https://example.com",
                "type": "json_api",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["posting_count"])
        self.assertIsNone(response.json()["health"])

    def test_created_board_defaults_active_true(self):
        response = self.client.post(
            "/api/boards",
            json={
                "name": "Example",
                "url": "https://example.com",
                "type": "html_crawl",
            },
        )
        self.assertTrue(response.json()["active"])


class TestUpdateBoard(BoardsRouterTestCase):
    def test_renames_and_re_urls_a_board(self):
        board_id = self._create()
        response = self.client.put(
            f"/api/boards/{board_id}",
            json={
                "name": "Renamed",
                "url": "https://renamed.example.com",
                "active": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Renamed")
        self.assertEqual(response.json()["url"], "https://renamed.example.com")

    def test_deactivating_persists_and_reads_back(self):
        board_id = self._create()

        response = self.client.put(
            f"/api/boards/{board_id}",
            json={
                "name": "Example",
                "url": "https://example.com",
                "active": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["active"])

        listed = self.client.get("/api/boards").json()["items"][0]
        self.assertFalse(listed["active"])

    def test_changing_the_type_is_409(self):
        board_id = self._create(type_="html_crawl")

        response = self.client.put(
            f"/api/boards/{board_id}",
            json={
                "name": "Example",
                "url": "https://example.com",
                "active": True,
                "type": "json_api",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"], "A board's type is fixed at creation"
        )
        self.assertEqual(
            self.client.get("/api/boards").json()["items"][0]["type"], "html_crawl"
        )

    def test_resending_the_unchanged_type_is_allowed(self):
        board_id = self._create(type_="html_crawl")

        response = self.client.put(
            f"/api/boards/{board_id}",
            json={
                "name": "Renamed",
                "url": "https://example.com",
                "active": True,
                "type": "html_crawl",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Renamed")

    def test_duplicate_name_is_409(self):
        self._create(name="Taken", url="https://taken.example.com")
        board_id = self._create(name="Example", url="https://example.com")

        response = self.client.put(
            f"/api/boards/{board_id}",
            json={"name": "Taken", "url": "https://example.com", "active": True},
        )
        self.assertEqual(response.status_code, 409)

    def test_duplicate_url_is_409(self):
        self._create(name="Taken", url="https://taken.example.com")
        board_id = self._create(name="Example", url="https://example.com")

        response = self.client.put(
            f"/api/boards/{board_id}",
            json={
                "name": "Example",
                "url": "https://taken.example.com",
                "active": True,
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_unknown_id_is_404(self):
        response = self.client.put(
            f"/api/boards/{uuid.uuid4()}",
            json={"name": "X", "url": "https://x.example.com", "active": True},
        )
        self.assertEqual(response.status_code, 404)


class TestDeleteBoard(BoardsRouterTestCase):
    def test_delete_then_404(self):
        board_id = self._create()

        response = self.client.delete(f"/api/boards/{board_id}")
        self.assertEqual(response.status_code, 204)

        missing = self.client.delete(f"/api/boards/{board_id}")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
