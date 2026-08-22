import os
import unittest
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from scraper.models import (
    START_URL_TYPE_HTML_CRAWL,
    START_URL_TYPE_JSON_API,
    Base,
    StartUrl,
)
from scraper.spiders.discovery_spider import DiscoverySpider


# sqlite has no JSONB/UUID types, and Base.metadata.create_all() would fail
# against it otherwise. Rendering them as TEXT is safe because only row
# selection is under test here, not the columns' real types.
@compiles(JSONB, "sqlite")
@compiles(UUID, "sqlite")
def _render_as_text_on_sqlite(element, compiler, **kw):
    return "TEXT"


class _FixtureSpider(DiscoverySpider):
    """Overrides the real board's start URLs so the fallback path is exercised."""

    name = "fixture"
    start_urls = ["https://example.com/literal-a", "https://example.com/literal-b"]


class TestLoadStartUrls(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()

    def test_returns_only_html_crawl_rows_ordered_by_name(self):
        self.session.add_all(
            [
                StartUrl(
                    name="zeta",
                    url="https://zeta.example.com",
                    type=START_URL_TYPE_HTML_CRAWL,
                ),
                StartUrl(
                    name="alpha",
                    url="https://alpha.example.com",
                    type=START_URL_TYPE_HTML_CRAWL,
                ),
                StartUrl(
                    name="beta-api",
                    url="https://beta.example.com/api",
                    type=START_URL_TYPE_JSON_API,
                ),
            ]
        )
        self.session.commit()

        pairs = _FixtureSpider.load_start_urls(self.session)

        self.assertEqual(
            [url for _id, url in pairs],
            ["https://alpha.example.com", "https://zeta.example.com"],
        )

    def test_falls_back_to_class_literal_when_table_empty(self):
        pairs = _FixtureSpider.load_start_urls(self.session)

        self.assertEqual(
            pairs,
            [
                (None, "https://example.com/literal-a"),
                (None, "https://example.com/literal-b"),
            ],
        )

    def test_does_not_fall_back_when_table_holds_only_json_api_rows(self):
        self.session.add(
            StartUrl(
                name="only-api",
                url="https://api.example.com",
                type=START_URL_TYPE_JSON_API,
            )
        )
        self.session.commit()

        with self.assertLogs(
            "scraper.spiders.discovery_spider", level="WARNING"
        ) as logs:
            pairs = _FixtureSpider.load_start_urls(self.session)

        self.assertEqual(pairs, [])
        self.assertTrue(any("skipped" in message for message in logs.output))

    def test_does_not_warn_when_html_crawl_rows_are_returned(self):
        self.session.add(
            StartUrl(
                name="alpha",
                url="https://alpha.example.com",
                type=START_URL_TYPE_HTML_CRAWL,
            )
        )
        self.session.commit()

        with self.assertNoLogs("scraper.spiders.discovery_spider", level="WARNING"):
            pairs = _FixtureSpider.load_start_urls(self.session)

        self.assertEqual(len(pairs), 1)


class TestDiscoverySpiderFromCrawler(unittest.TestCase):
    def _make_crawler(
        self, redis_host: str = "cluster-redis", redis_port: int = 6380
    ) -> MagicMock:
        crawler = MagicMock()
        crawler.settings.get.return_value = redis_host
        crawler.settings.getint.return_value = redis_port
        return crawler

    @patch("scraper.spiders.discovery_spider.redis.Redis")
    def test_from_crawler_passes_credentials_from_env(self, mock_redis_cls):
        crawler = self._make_crawler()
        with patch.dict(
            os.environ, {"REDIS_USERNAME": "user", "REDIS_PASSWORD": "password"}
        ):
            DiscoverySpider.from_crawler(crawler)

        self.assertEqual(mock_redis_cls.call_args.kwargs["host"], "cluster-redis")
        self.assertEqual(mock_redis_cls.call_args.kwargs["port"], 6380)
        self.assertEqual(mock_redis_cls.call_args.kwargs["username"], "user")
        self.assertEqual(mock_redis_cls.call_args.kwargs["password"], "password")

    @patch("scraper.spiders.discovery_spider.redis.Redis")
    def test_from_crawler_passes_none_credentials_when_unset(self, mock_redis_cls):
        crawler = self._make_crawler()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_USERNAME", None)
            os.environ.pop("REDIS_PASSWORD", None)
            DiscoverySpider.from_crawler(crawler)

        self.assertIsNone(mock_redis_cls.call_args.kwargs["username"])
        self.assertIsNone(mock_redis_cls.call_args.kwargs["password"])


class TestStartRequests(unittest.TestCase):
    @patch("scraper.spiders.discovery_spider.SessionLocal")
    def test_yields_one_request_per_pair_tagged_with_its_start_url_id(
        self, mock_session_local
    ):
        spider = DiscoverySpider()
        first_id = uuid.uuid4()
        pairs = [(first_id, "https://a.example.com"), (None, "https://b.example.com")]
        with patch.object(DiscoverySpider, "load_start_urls", return_value=pairs):
            requests = list(spider.start_requests())

        self.assertEqual([r.url for r in requests], [url for _id, url in pairs])
        self.assertEqual(requests[0].meta["start_url_id"], first_id)
        self.assertIsNone(requests[1].meta["start_url_id"])
        mock_session_local.return_value.close.assert_called_once()


class TestParseJob(unittest.TestCase):
    def test_carries_start_url_id_from_response_meta_into_the_item(self):
        spider = DiscoverySpider()
        start_url_id = uuid.uuid4()
        response = MagicMock()
        response.url = "https://a.example.com/job/1"
        response.text = "<html>job</html>"
        response.meta = {"start_url_id": start_url_id}

        items = list(spider.parse_job(response))

        self.assertEqual(items[0]["start_url_id"], str(start_url_id))

    def test_absent_start_url_id_stays_none(self):
        spider = DiscoverySpider()
        response = MagicMock()
        response.url = "https://a.example.com/job/1"
        response.text = "<html>job</html>"
        response.meta = {}

        items = list(spider.parse_job(response))

        self.assertIsNone(items[0]["start_url_id"])


if __name__ == "__main__":
    unittest.main()
