import json
import unittest
from unittest.mock import MagicMock

from scrapy.http import Request, Response

from adapters.adapters.mapping import MappedIndex
from scraper.spiders.discovery_spider import DiscoverySpider


def _api_response(url, body: bytes, *, headers=None, meta=None):
    """A real Response, not a mock, so header/body handling genuinely runs."""
    request = Request(url=url, meta=meta or {})
    return Response(url=url, body=body, headers=headers, request=request)


def _json_body(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


_SIMPLE_INDEX_DOCUMENT = {
    "version": 1,
    "type": "index",
    "domains": ["api.example.com"],
    "jmespath": {"postings": "jobs[]", "job_url": "url"},
}


class TestParseApiFilters(unittest.TestCase):
    """Filter semantics driven through the spider callback that applies them."""

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

    def _response_with_filter(self, jobs, filter_qs):
        stored_url = f"https://api.example.com/jobs?{filter_qs}"
        return self._response(jobs, stored_url=stored_url)

    def test_two_values_on_one_key_select_either(self):
        jobs = [
            {"url": "https://x.example/1", "offices": [{"name": "Berlin"}]},
            {"url": "https://x.example/2", "offices": [{"name": "Zurich"}]},
            {"url": "https://x.example/3", "offices": [{"name": "Paris"}]},
        ]
        response = self._response_with_filter(
            jobs, "filter.offices[].name=Berlin&filter.offices[].name=Zurich"
        )

        items = list(self.spider.parse_api(response))

        self.assertEqual(
            {i["url"] for i in items}, {"https://x.example/1", "https://x.example/2"}
        )

    def test_two_different_keys_must_both_match(self):
        jobs = [
            {
                "url": "https://x.example/1",
                "offices": [{"name": "Berlin"}],
                "remote": "true",
            },
            {
                "url": "https://x.example/2",
                "offices": [{"name": "Berlin"}],
                "remote": "false",
            },
        ]
        response = self._response_with_filter(
            jobs, "filter.offices[].name=Berlin&filter.remote=true"
        )

        items = list(self.spider.parse_api(response))

        self.assertEqual([i["url"] for i in items], ["https://x.example/1"])

    def test_unresolved_path_logs_operator_error_and_yields_nothing(self):
        jobs = [{"url": "https://x.example/1", "offices": [{"name": "Berlin"}]}]
        response = self._response_with_filter(jobs, "filter.ofices[].name=Berlin")

        with self.assertLogs("scraper.spiders.posting_filters", level="ERROR") as logs:
            results = list(self.spider.parse_api(response))

        self.assertEqual(results, [])
        self.assertTrue(any("ofices" in line for line in logs.output))

    def test_resolved_but_matching_nothing_yields_nothing_and_logs_no_error(self):
        jobs = [{"url": "https://x.example/1", "offices": [{"name": "Berlin"}]}]
        response = self._response_with_filter(jobs, "filter.offices[].name=Singapore")

        with self.assertNoLogs("scraper.spiders.posting_filters", level="ERROR"):
            results = list(self.spider.parse_api(response))

        self.assertEqual(results, [])

    def test_all_references_without_a_document_logs_no_operator_error(self):
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
        response = self._response_with_filter([{}], "filter.offices[].name=Berlin")

        with self.assertNoLogs("scraper.spiders.posting_filters", level="ERROR"):
            results = list(self.spider.parse_api(response))

        self.assertEqual(len(results), 1)

    def test_filter_false_selects_the_json_boolean_false_and_logs_no_error(self):
        jobs = [
            {"url": "https://x.example/1", "remote": False},
            {"url": "https://x.example/2", "remote": True},
        ]
        response = self._response_with_filter(jobs, "filter.remote=false")

        with self.assertNoLogs("scraper.spiders.posting_filters", level="ERROR"):
            items = list(self.spider.parse_api(response))

        self.assertEqual([i["url"] for i in items], ["https://x.example/1"])

    def test_filter_true_selects_the_json_boolean_true_not_the_text_true(self):
        jobs = [
            {"url": "https://x.example/1", "remote": True},
            {"url": "https://x.example/2", "remote": "True"},
        ]
        response = self._response_with_filter(jobs, "filter.remote=true")

        items = list(self.spider.parse_api(response))

        self.assertEqual([i["url"] for i in items], ["https://x.example/1"])

    def test_a_raising_filter_key_drops_only_that_posting(self):
        jobs = [
            {"url": "https://x.example/1", "content": ["not", "a", "string"]},
            {"url": "https://x.example/2", "content": "ok"},
        ]
        response = self._response_with_filter(jobs, "filter.markdown(content)=ok")

        with self.assertLogs("scraper.spiders.posting_filters", level="ERROR"):
            items = list(self.spider.parse_api(response))

        self.assertEqual([i["url"] for i in items], ["https://x.example/2"])

    def test_a_filter_key_failing_its_preloop_check_refuses_the_whole_response(self):
        jobs = [{"url": "https://x.example/1"}]
        response = self._response_with_filter(jobs, "filter.no_such_fn(title)=x")

        with self.assertLogs("scraper.spiders.posting_filters", level="ERROR"):
            results = list(self.spider.parse_api(response))

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
