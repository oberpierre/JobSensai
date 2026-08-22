import os
import unittest
from unittest.mock import MagicMock, patch

from scraper.spiders.discovery_spider import DiscoverySpider


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


if __name__ == "__main__":
    unittest.main()
