import unittest
import uuid
from collections.abc import Iterator

from scraper.spiders.base_spider import BaseJobSpider


class _FixtureSpider(BaseJobSpider):
    """Minimal concrete spider so create_item can be exercised."""

    name = "fixture"
    start_urls = ["https://example.com/literal-a"]

    def parse(self, response) -> Iterator:
        return iter(())

    def parse_job(self, response) -> Iterator:
        return iter(())


class TestCreateItem(unittest.TestCase):
    def test_sets_url_html_and_start_url_id(self):
        spider = _FixtureSpider()
        start_url_id = uuid.uuid4()

        item = spider.create_item(
            url="https://example.com/job/1",
            html="<html/>",
            start_url_id=start_url_id,
        )

        self.assertEqual(item["url"], "https://example.com/job/1")
        self.assertEqual(item["html_content"], "<html/>")
        self.assertEqual(item["start_url_id"], str(start_url_id))
        self.assertEqual(item["metadata"]["spider_name"], "fixture")

    def test_absent_start_url_id_stays_none(self):
        spider = _FixtureSpider()

        item = spider.create_item(url="https://example.com/job/1", html="<html/>")

        self.assertIsNone(item["start_url_id"])


if __name__ == "__main__":
    unittest.main()
