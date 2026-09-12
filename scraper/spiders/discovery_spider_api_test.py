import json
import unittest
from unittest.mock import MagicMock, patch

from scrapy.http import Request, TextResponse

from adapters.adapters.mapping import MappedIndex
from scraper.models import START_URL_TYPE_API
from scraper.spiders.discovery_spider import DiscoverySpider


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
