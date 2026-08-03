import os
import unittest
from unittest.mock import MagicMock, patch

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


if __name__ == "__main__":
    unittest.main()
