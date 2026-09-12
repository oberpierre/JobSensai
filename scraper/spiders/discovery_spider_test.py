import json
import os
import unittest
import uuid
from unittest.mock import MagicMock, patch

from scrapy.http import HtmlResponse, Request, TextResponse
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from adapters.adapters.mapping import MappedIndex
from scraper.models import (
    START_URL_TYPE_API,
    START_URL_TYPE_HTML_CRAWL,
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


class TestLoadStartUrls(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()

    def test_returns_both_html_crawl_and_api_rows_ordered_by_name(self):
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
                    type=START_URL_TYPE_API,
                ),
            ]
        )
        self.session.commit()

        rows = DiscoverySpider.load_start_urls(self.session)

        self.assertEqual(
            [(url, t) for _id, url, t in rows],
            [
                ("https://alpha.example.com", START_URL_TYPE_HTML_CRAWL),
                ("https://beta.example.com/api", START_URL_TYPE_API),
                ("https://zeta.example.com", START_URL_TYPE_HTML_CRAWL),
            ],
        )

    def test_returns_only_active_html_crawl_rows(self):
        self.session.add_all(
            [
                StartUrl(
                    name="active-one",
                    url="https://active.example.com",
                    type=START_URL_TYPE_HTML_CRAWL,
                    active=True,
                ),
                StartUrl(
                    name="inactive-one",
                    url="https://inactive.example.com",
                    type=START_URL_TYPE_HTML_CRAWL,
                    active=False,
                ),
            ]
        )
        self.session.commit()

        rows = DiscoverySpider.load_start_urls(self.session)

        self.assertEqual([url for _id, url, _t in rows], ["https://active.example.com"])

    def test_warns_once_when_every_row_is_inactive(self):
        self.session.add_all(
            [
                StartUrl(
                    name="alpha",
                    url="https://alpha.example.com",
                    type=START_URL_TYPE_HTML_CRAWL,
                    active=False,
                ),
                StartUrl(
                    name="beta",
                    url="https://beta.example.com",
                    type=START_URL_TYPE_HTML_CRAWL,
                    active=False,
                ),
            ]
        )
        self.session.commit()

        with self.assertLogs(
            "scraper.spiders.discovery_spider", level="WARNING"
        ) as logs:
            rows = DiscoverySpider.load_start_urls(self.session)

        self.assertEqual(rows, [])
        self.assertEqual(len(logs.output), 1)
        # The one warning has to name inactivity, or a later rewrite can drop that
        # cause and leave an operator reading a line about the wrong one.
        self.assertIn("active", logs.output[0])

    def test_empty_table_yields_no_pairs_and_logs(self):
        with self.assertLogs(
            "scraper.spiders.discovery_spider", level="WARNING"
        ) as logs:
            rows = DiscoverySpider.load_start_urls(self.session)

        self.assertEqual(rows, [])
        # The count, not just the warning: one message now covers the empty table and
        # the table whose every row was filtered out, and only the number tells an
        # operator which of the two they are looking at.
        self.assertIn("out of 0 configured", logs.output[0])

    def test_table_holding_only_api_rows_yields_them_and_does_not_warn(self):
        self.session.add(
            StartUrl(
                name="only-api",
                url="https://api.example.com",
                type=START_URL_TYPE_API,
            )
        )
        self.session.commit()

        with self.assertNoLogs("scraper.spiders.discovery_spider", level="WARNING"):
            rows = DiscoverySpider.load_start_urls(self.session)

        self.assertEqual(
            [(url, t) for _id, url, t in rows],
            [("https://api.example.com", START_URL_TYPE_API)],
        )

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
            rows = DiscoverySpider.load_start_urls(self.session)

        self.assertEqual(len(rows), 1)


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
    def test_yields_one_request_per_html_crawl_row_tagged_with_its_start_url_id(
        self, mock_session_local
    ):
        spider = DiscoverySpider()
        first_id = uuid.uuid4()
        rows = [
            (first_id, "https://a.example.com", START_URL_TYPE_HTML_CRAWL),
            (None, "https://b.example.com", START_URL_TYPE_HTML_CRAWL),
        ]
        with patch.object(DiscoverySpider, "load_start_urls", return_value=rows):
            requests = list(spider.start_requests())

        self.assertEqual([r.url for r in requests], [url for _id, url, _t in rows])
        self.assertEqual([r.callback for r in requests], [spider.parse, spider.parse])
        self.assertEqual(requests[0].meta["start_url_id"], first_id)
        self.assertIsNone(requests[1].meta["start_url_id"])
        mock_session_local.return_value.close.assert_called_once()

    @patch("scraper.spiders.discovery_spider.SessionLocal")
    def test_an_api_row_is_sent_to_parse_api_at_the_stripped_url(
        self, mock_session_local
    ):
        spider = DiscoverySpider()
        stored_id = uuid.uuid4()
        stored_url = "https://api.example.com/jobs?filter.offices[].name=Berlin&x=1"
        rows = [(stored_id, stored_url, START_URL_TYPE_API)]
        with patch.object(DiscoverySpider, "load_start_urls", return_value=rows):
            requests = list(spider.start_requests())

        self.assertEqual(requests[0].callback, spider.parse_api)
        self.assertEqual(requests[0].url, "https://api.example.com/jobs?x=1")
        self.assertEqual(requests[0].meta["start_url_id"], stored_id)
        self.assertEqual(requests[0].meta["stored_url"], stored_url)


def _html_response(url, *, headers=None, meta=None):
    """A real Response, not a mock, so header normalisation genuinely runs."""
    request = Request(url=url, meta=meta or {})
    return HtmlResponse(
        url=url,
        body=b"<html>job</html>",
        encoding="utf-8",
        headers=headers,
        request=request,
    )


class TestParseJob(unittest.TestCase):
    def test_carries_start_url_id_from_response_meta_into_the_item(self):
        spider = DiscoverySpider()
        start_url_id = uuid.uuid4()
        response = _html_response(
            "https://a.example.com/job/1", meta={"start_url_id": start_url_id}
        )

        items = list(spider.parse_job(response))

        self.assertEqual(items[0]["start_url_id"], str(start_url_id))

    def test_absent_start_url_id_stays_none(self):
        spider = DiscoverySpider()
        response = _html_response("https://a.example.com/job/1")

        items = list(spider.parse_job(response))

        self.assertIsNone(items[0]["start_url_id"])

    def test_sets_source_url_from_the_response(self):
        spider = DiscoverySpider()
        response = _html_response("https://a.example.com/job/1")

        items = list(spider.parse_job(response))

        self.assertEqual(items[0]["source_url"], "https://a.example.com/job/1")

    def test_strips_content_type_parameters_off_a_real_header(self):
        spider = DiscoverySpider()
        response = _html_response(
            "https://a.example.com/job/1",
            headers={"Content-Type": "text/html; charset=UTF-8"},
        )

        items = list(spider.parse_job(response))

        self.assertEqual(items[0]["content_type"], "text/html")

    def test_defaults_content_type_when_the_response_carries_no_header(self):
        spider = DiscoverySpider()
        response = _html_response("https://a.example.com/job/1")

        items = list(spider.parse_job(response))

        self.assertEqual(items[0]["content_type"], "text/html")


def _api_response(url, body: bytes, *, headers=None, meta=None):
    """A real TextResponse, not a mock, so a `response.text` implementation
    genuinely decodes the body rather than raising."""
    request = Request(url=url, meta=meta or {})
    return TextResponse(url=url, body=body, headers=headers, request=request)


def _json_body(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


_SIMPLE_INDEX_DOCUMENT = {
    "version": 1,
    "type": "index",
    "domains": ["api.example.com"],
    "jmespath": {"postings": "jobs[]", "posting_url": "url"},
}


class ParseApiTestCase(unittest.TestCase):
    """Shared fixture: a synthetic index mapping installed on the spider's registry."""

    def setUp(self):
        self.spider = DiscoverySpider()
        self.spider.redis_client = MagicMock()
        self.mapping = MappedIndex(_SIMPLE_INDEX_DOCUMENT)
        self.spider.registry.get_index_mapping = lambda url: self.mapping

    def _response(self, jobs, *, stored_url="https://api.example.com/jobs", **kw):
        return _api_response(
            "https://api.example.com/jobs",
            _json_body({"jobs": jobs}),
            meta={"stored_url": stored_url, "start_url_id": None},
            **kw,
        )


class TestParseApiBasics(ParseApiTestCase):
    def test_one_item_per_posting_round_trips_and_preserves_non_ascii(self):
        posting = {"url": "https://x.example/1", "title": "Zürich"}
        response = self._response([posting])

        items = list(self.spider.parse_api(response))

        self.assertEqual(len(items), 1)
        self.assertEqual(json.loads(items[0]["raw_content"]), posting)
        self.assertIn("Zürich", items[0]["raw_content"])
        self.assertNotIn("\\u", items[0]["raw_content"])

    def test_document_carrying_reference_yields_no_request(self):
        response = self._response([{"url": "https://x.example/1"}])

        results = list(self.spider.parse_api(response))

        self.assertEqual(len(results), 1)
        self.assertFalse(any(isinstance(r, Request) for r in results))

    def test_reference_without_document_yields_a_request_and_no_item(self):
        # Builds the PostingRef directly to exercise the spider's branch in
        # isolation; the test below covers the same branch end to end.
        from adapters.adapters.base import PostingRef

        self.spider.registry.get_index_mapping = lambda url: type(
            "M",
            (),
            {
                "references": lambda self, doc, url: [
                    PostingRef(url="https://x.example/1", document=None)
                ]
            },
        )()

        response = self._response([{}])
        results = list(self.spider.parse_api(response))

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], Request)
        self.assertEqual(results[0].callback, self.spider.parse_job)

    def test_bare_id_feed_yields_requests_and_no_items(self):
        self.spider.registry.get_index_mapping = lambda url: MappedIndex(
            {
                "version": 1,
                "type": "index",
                "domains": ["api.example.com"],
                "jmespath": {
                    "postings": "jobs[]",
                    "posting_url": "join('', ['https://api.example.com/jobs/', @])",
                },
            }
        )
        response = self._response(["1234", "1345"])

        results = list(self.spider.parse_api(response))

        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(r, Request) for r in results))
        self.assertTrue(all(r.callback == self.spider.parse_job for r in results))

    def test_bare_json_array_body_yields_one_item_per_element(self):
        response = _api_response(
            "https://api.example.com/jobs",
            _json_body(
                [{"url": "https://x.example/1"}, {"url": "https://x.example/2"}]
            ),
            meta={"stored_url": "https://api.example.com/jobs", "start_url_id": None},
        )
        self.spider.registry.get_index_mapping = lambda url: MappedIndex(
            {
                "version": 1,
                "type": "index",
                "domains": ["api.example.com"],
                "jmespath": {"postings": "[]", "posting_url": "url"},
            }
        )

        items = list(self.spider.parse_api(response))

        self.assertEqual(len(items), 2)

    def test_item_content_type_is_the_literal_regardless_of_header_spelling(self):
        response = self._response(
            [{"url": "https://x.example/1"}],
            headers={"Content-Type": "Application/JSON"},
        )

        items = list(self.spider.parse_api(response))

        self.assertEqual(items[0]["content_type"], "application/json")

    def test_no_index_mapping_logs_error_and_enqueues_nothing(self):
        self.spider.registry.get_index_mapping = lambda url: None
        response = self._response([{"url": "https://x.example/1"}])

        with self.assertLogs("scraper.spiders.discovery_spider", level="ERROR"):
            results = list(self.spider.parse_api(response))

        self.assertEqual(results, [])
        self.spider.redis_client.lpush.assert_not_called()

    def test_body_that_does_not_parse_as_json_logs_and_yields_nothing(self):
        response = _api_response(
            "https://api.example.com/jobs",
            b"<html>not json</html>",
            headers={"Content-Type": "application/json"},
            meta={"stored_url": "https://api.example.com/jobs", "start_url_id": None},
        )

        with self.assertLogs("scraper.spiders.discovery_spider", level="ERROR"):
            results = list(self.spider.parse_api(response))

        self.assertEqual(results, [])

    def test_a_json_scalar_body_is_refused(self):
        response = _api_response(
            "https://api.example.com/jobs",
            b'"maintenance"',
            meta={"stored_url": "https://api.example.com/jobs", "start_url_id": None},
        )

        with self.assertLogs("scraper.spiders.discovery_spider", level="ERROR"):
            results = list(self.spider.parse_api(response))

        self.assertEqual(results, [])

    def test_mismatched_content_type_over_a_json_body_yields_items_and_logs_info(self):
        response = self._response(
            [{"url": "https://x.example/1"}], headers={"Content-Type": "text/plain"}
        )

        with self.assertLogs("scraper.spiders.discovery_spider", level="INFO") as logs:
            items = list(self.spider.parse_api(response))

        self.assertEqual(len(items), 1)
        self.assertTrue(any("text/plain" in line for line in logs.output))

    def test_charset_lie_over_utf8_bytes_stores_the_correct_text(self):
        posting = {"url": "https://x.example/1", "title": "Zürich"}
        response = self._response(
            [posting], headers={"Content-Type": "text/plain; charset=iso-8859-1"}
        )

        items = list(self.spider.parse_api(response))

        self.assertIn("Zürich", items[0]["raw_content"])
        self.assertNotIn("Ã¼", items[0]["raw_content"])


class TestParseApiFilters(ParseApiTestCase):
    def _response_with_filter(self, jobs, filter_qs):
        stored_url = f"https://api.example.com/jobs?{filter_qs}"
        return self._response(jobs, stored_url=stored_url)

    def test_filtered_out_posting_produces_no_item_at_all(self):
        jobs = [{"url": "https://x.example/1", "offices": [{"name": "Paris"}]}]
        response = self._response_with_filter(jobs, "filter.offices[].name=Berlin")

        results = list(self.spider.parse_api(response))

        self.assertEqual(results, [])

    def test_filter_param_is_absent_from_the_url_actually_requested(self):
        stored_url = "https://api.example.com/jobs?filter.remote=true&content=true"
        rows = [(None, stored_url, START_URL_TYPE_API)]
        with (
            patch.object(DiscoverySpider, "load_start_urls", return_value=rows),
            patch("scraper.spiders.discovery_spider.SessionLocal"),
        ):
            requests = list(self.spider.start_requests())

        self.assertNotIn("filter.", requests[0].url)
        self.assertIn("content=true", requests[0].url)


if __name__ == "__main__":
    unittest.main()
