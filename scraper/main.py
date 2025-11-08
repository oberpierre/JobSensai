#!/usr/bin/env python3
"""Main entry point for JobSensai scraper.

Usage:
    bazel run //scraper:main -- <spider_name>

Examples:
    bazel run //scraper:main -- indeed
    bazel run //scraper:main -- linkedin
"""

import settings
from scrapy.crawler import CrawlerProcess
from spiders.google_spider import GoogleSpider


def main() -> None:
    """Run Scrapy crawler."""
    process = CrawlerProcess(settings=vars(settings))
    process.crawl(GoogleSpider)
    process.start()


if __name__ == "__main__":
    main()
