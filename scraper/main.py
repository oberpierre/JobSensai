#!/usr/bin/env python3
"""Main entry point for JobSensai scraper.

Usage:
    bazel run //scraper:main -- <spider_name>

Examples:
    bazel run //scraper:main -- indeed
    bazel run //scraper:main -- linkedin
"""

from dotenv import load_dotenv
from scrapy.crawler import CrawlerProcess

load_dotenv()
# Build settings (must be imported AFTER load_dotenv)


def main() -> None:
    """Run Scrapy crawler."""
    import settings
    from spiders.google_spider import GoogleSpider
    # Filter settings to only include valid configuration (uppercase variables)
    # This avoids passing imported modules (like 'os') which cause pickling errors
    conf = {k: v for k, v in vars(settings).items() if k.isupper()}
    process = CrawlerProcess(settings=conf)
    process.crawl(GoogleSpider)
    process.start()


if __name__ == "__main__":
    main()
