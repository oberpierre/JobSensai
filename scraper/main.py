#!/usr/bin/env python3
"""Main entry point for JobSensai scraper.

Usage:
    bazel run //scraper:main -- <spider_name>

Examples:
    bazel run //scraper:main -- indeed
    bazel run //scraper:main -- linkedin
"""

import sys
from collections.abc import Mapping

from dotenv import load_dotenv
from scrapy.crawler import CrawlerProcess

load_dotenv()
# Build settings (must be imported AFTER load_dotenv)


def crawl_outcome(stats: Mapping[str, object]) -> tuple[int, str]:
    """Decide the crawl's exit code and reason from Scrapy's stats mapping.

    The spider re-scrapes every listing on every run, so zero items scraped
    is a failure rather than "nothing new to find".
    """
    if not stats.get("item_scraped_count"):
        return 1, "no items scraped"
    error_count = stats.get("log_count/ERROR", 0)
    if error_count:
        return 1, f"{error_count} error(s) logged"
    return 0, "ok"


def main() -> None:
    """Run Scrapy crawler; exit non-zero if it scraped nothing or logged an error."""
    import scraper.settings as settings
    from scraper.spiders.google_spider import GoogleSpider

    # Filter settings to only include valid configuration (uppercase variables)
    # This avoids passing imported modules (like 'os') which cause pickling errors
    conf = {k: v for k, v in vars(settings).items() if k.isupper()}
    process = CrawlerProcess(settings=conf)
    crawler = process.create_crawler(GoogleSpider)
    process.crawl(crawler)
    process.start()

    exit_code, reason = crawl_outcome(crawler.stats.get_stats())
    if exit_code != 0:
        print(reason, file=sys.stderr)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
