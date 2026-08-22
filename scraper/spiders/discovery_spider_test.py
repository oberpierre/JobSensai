import os
import unittest
import uuid
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
