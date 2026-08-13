import os
import unittest

from scraper import settings
from scraper.main import crawl_outcome


class TestCrawlOutcome(unittest.TestCase):
    def test_broken_run_observed_in_production_is_failure(self):
        # The shape logged when HTTPCACHE_DIR was unwritable: two requests,
        # two download errors, no items key at all.
        stats = {
            "downloader/request_count": 2,
            "downloader/request_method_count/GET": 2,
            "log_count/ERROR": 2,
            "log_count/INFO": 10,
            "finish_reason": "finished",
        }
        code, reason = crawl_outcome(stats)
        self.assertEqual(code, 1)
        self.assertTrue(reason)

    def test_healthy_run_is_success(self):
        stats = {
            "downloader/request_count": 5,
            "item_scraped_count": 3,
            "log_count/INFO": 8,
            "finish_reason": "finished",
        }
        code, _reason = crawl_outcome(stats)
        self.assertEqual(code, 0)

    def test_items_scraped_but_errors_logged_is_failure(self):
        stats = {
            "item_scraped_count": 3,
            "log_count/ERROR": 1,
            "finish_reason": "finished",
        }
        code, _reason = crawl_outcome(stats)
        self.assertEqual(code, 1)

    def test_zero_items_scraped_is_failure(self):
        stats = {
            "item_scraped_count": 0,
            "log_count/ERROR": 0,
            "finish_reason": "finished",
        }
        code, _reason = crawl_outcome(stats)
        self.assertEqual(code, 1)


class TestHttpcacheDir(unittest.TestCase):
    def test_httpcache_dir_is_absolute(self):
        # data_path() joins a relative value under .scrapy, which the crawler's
        # non-root user can't create, so regressing to a relative path silently
        # drops every cached response again.
        self.assertTrue(os.path.isabs(settings.HTTPCACHE_DIR))


if __name__ == "__main__":
    unittest.main()
