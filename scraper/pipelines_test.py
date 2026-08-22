import json
import os
import unittest
import uuid
from unittest.mock import MagicMock, patch

from scraper.items import RawJobItem
from scraper.models import RawJobPosting
from scraper.pipelines import BronzeLayerPipeline


class TestBronzeLayerPipeline(unittest.TestCase):
    def setUp(self):
        self.pipeline = BronzeLayerPipeline(redis_host="localhost", redis_port=6379)
        self.spider = MagicMock()
        self.spider.name = "test_spider"

    @patch("scraper.pipelines.redis.Redis")
    def test_open_spider_passes_credentials_from_env(self, mock_redis_cls):
        with patch.dict(
            os.environ, {"REDIS_USERNAME": "user", "REDIS_PASSWORD": "password"}
        ):
            self.pipeline.open_spider(self.spider)

        self.assertEqual(mock_redis_cls.call_args.kwargs["username"], "user")
        self.assertEqual(mock_redis_cls.call_args.kwargs["password"], "password")

    @patch("scraper.pipelines.redis.Redis")
    def test_open_spider_passes_none_credentials_when_unset(self, mock_redis_cls):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_USERNAME", None)
            os.environ.pop("REDIS_PASSWORD", None)
            self.pipeline.open_spider(self.spider)

        self.assertIsNone(mock_redis_cls.call_args.kwargs["username"])
        self.assertIsNone(mock_redis_cls.call_args.kwargs["password"])


class TestProcessItemCarriesStartUrlId(unittest.TestCase):
    def setUp(self):
        self.pipeline = BronzeLayerPipeline(redis_host="localhost", redis_port=6379)
        self.spider = MagicMock()
        self.spider.name = "test_spider"

    def test_raw_job_posting_built_from_the_pushed_item_carries_start_url_id(self):
        # process_item only forwards the item to Redis, so the round trip
        # through a RawJobPosting proves the field survives that JSON hop intact.
        self.pipeline.redis_client = MagicMock()
        start_url_id = uuid.uuid4()
        item = RawJobItem()
        item["url"] = "https://example.com/job/1"
        item["html_content"] = "<html/>"
        item["start_url_id"] = str(start_url_id)
        item["metadata"] = {"spider_name": "test_spider"}

        self.pipeline.process_item(item, self.spider)

        pushed_item = json.loads(self.pipeline.redis_client.lpush.call_args.args[1])[
            "item"
        ]
        posting = RawJobPosting(
            url=pushed_item["url"],
            html_content=pushed_item["html_content"],
            start_url_id=pushed_item["start_url_id"],
        )
        self.assertEqual(str(posting.start_url_id), str(start_url_id))


if __name__ == "__main__":
    unittest.main()
