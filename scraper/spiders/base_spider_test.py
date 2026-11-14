import unittest
import uuid
from collections.abc import Iterator

from scraper.spiders.base_spider import BaseJobSpider


class _FixtureSpider(BaseJobSpider):
    """Minimal concrete spider so create_item can be exercised."""

    name = "fixture"

    def parse(self, response) -> Iterator:
        return iter(())

    def parse_job(self, response) -> Iterator:
        return iter(())


class TestCreateItem(unittest.TestCase):
    def test_sets_url_content_and_start_url_id(self):
        spider = _FixtureSpider()
        start_url_id = uuid.uuid4()

        item = spider.create_item(
            url="https://example.com/job/1",
            content="<html/>",
            start_url_id=start_url_id,
            source_url="https://example.com/job/1",
            content_type="text/html",
        )

        self.assertEqual(item["url"], "https://example.com/job/1")
        self.assertEqual(item["raw_content"], "<html/>")
        self.assertEqual(item["start_url_id"], str(start_url_id))
        self.assertEqual(item["metadata"]["spider_name"], "fixture")

    def test_absent_start_url_id_stays_none(self):
        spider = _FixtureSpider()

        item = spider.create_item(
            url="https://example.com/job/1",
            content="<html/>",
            source_url="https://example.com/job/1",
            content_type="text/html",
        )

        self.assertIsNone(item["start_url_id"])

    def test_source_url_and_content_type_pass_through_when_given(self):
        spider = _FixtureSpider()

        item = spider.create_item(
            url="https://example.com/job/1",
            content='{"title": "x"}',
            source_url="https://api.example.com/feed",
            content_type="application/json",
        )

        self.assertEqual(item["source_url"], "https://api.example.com/feed")
        self.assertEqual(item["content_type"], "application/json")

    def test_source_url_is_required(self):
        # A caller that omits it must fail where the item is built rather than
        # falling back to a plausible value the callee has no business guessing.
        spider = _FixtureSpider()

        with self.assertRaises(TypeError):
            spider.create_item(
                url="https://example.com/job/1",
                content="<html/>",
                content_type="text/html",
            )

    def test_content_type_is_required(self):
        spider = _FixtureSpider()

        with self.assertRaises(TypeError):
            spider.create_item(
                url="https://example.com/job/1",
                content="<html/>",
                source_url="https://example.com/job/1",
            )

    def test_start_url_id_is_keyword_only(self):
        # A positional 3rd argument must raise rather than silently bind to
        # start_url_id when it was meant as an arbitrary metadata value.
        spider = _FixtureSpider()

        with self.assertRaises(TypeError):
            spider.create_item(
                "https://example.com/job/1", "<html/>", "not-a-column-value"
            )


if __name__ == "__main__":
    unittest.main()
