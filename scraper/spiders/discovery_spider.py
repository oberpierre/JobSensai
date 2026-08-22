"""Example Indeed spider (template for implementation).

This is a placeholder spider showing the structure.
Actual implementation will require:
1. Analyzing Indeed's HTML structure
2. Handling pagination
3. Extracting job links
4. Handling rate limiting / anti-bot measures
"""

import json
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import redis
import scrapy
from scrapy.crawler import Crawler

from adapters.registry import AdapterRegistry
from scraper.items import RawJobItem
from scraper.spiders.base_spider import BaseJobSpider

logger = logging.getLogger(__name__)


class DiscoverySpider(BaseJobSpider):
    """Spider for scraping Google job postings."""

    name = "google"

    # TODO: Configure these based on search criteria
    start_urls = [
        "https://www.google.com/about/careers/applications/jobs/results/?location=Switzerland&location=Singapore&sort_by=date",
        # https://www.google.com/about/careers/applications/jobs/results/120830781164528326-program-manager-talent-outreach-talent-engagement?location=Switzerland&location=Singapore&sort_by=date
        # Greenhouse is read through its JSON board API instead, so crawling this HTML
        # path would teach an extraction adapter for a format being dropped, and would
        # tombstone every posting it ingested once the URL goes again.
        # "https://job-boards.greenhouse.io/anthropic?error=true&departments%5B%5D=4002061008&departments%5B%5D=4010154008&departments%5B%5D=4050633008&departments%5B%5D=4019632008",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.registry = AdapterRegistry()
        self.redis_client: redis.Redis | None = None

    @classmethod
    def from_crawler(cls, crawler: Crawler, *args: Any, **kwargs: Any):
        """Initialize spider and wire dependencies from Scrapy settings."""
        spider = super().from_crawler(crawler, *args, **kwargs)

        redis_host = crawler.settings.get("REDIS_HOST", "localhost")
        redis_port = crawler.settings.getint("REDIS_PORT", 6379)

        spider.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            username=os.getenv("REDIS_USERNAME") or None,
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )

        logger.info(
            "Initialized Redis client for spider %s at %s:%s",
            spider.name,
            redis_host,
            redis_port,
        )

        return spider

    def parse(self, response: scrapy.http.Response) -> Iterator[scrapy.Request]:
        """Extract job links from search results page."""
        logger.info(f"Parsing search page: {response.url}")

        adapter = self.registry.get_discovery_adapter(response.url)

        # If no adapter, log fallback and STOP spidering for this domain/url path
        if not adapter:
            logger.warning(
                f"No discovery adapter found for: {response.url}. "
                "Triggering discovery learning pipeline."
            )
            self._trigger_discovery_learning(response)
            return

        try:
            # 1. Job Links
            job_links = adapter.get_job_links(response.text, response.url)
            for link in job_links:
                yield response.follow(link, callback=self.parse_job)

            # 2. Next Page
            next_links = adapter.get_next_page_links(response.text, response.url)
            if next_links:  # might be None or []
                for link in next_links:
                    yield response.follow(link, callback=self.parse)
        except Exception as e:
            logger.error(f"Adapter logic failed on index page {response.url}: {e}")
            self._trigger_discovery_learning(response)

    def _trigger_discovery_learning(self, response: scrapy.http.Response):
        """Push listing HTML to discovery_learning_tasks queue.

        Payload schema (consumed by LLM worker):
          domain    – netloc extracted from the URL (required for deduplication lock)
          url       – full URL for context
          html      – raw page HTML
          timestamp – ISO-8601 string
        """
        from urllib.parse import urlsplit

        domain = urlsplit(response.url).netloc
        payload = {
            "domain": domain,
            "url": response.url,
            "html": response.text,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if not self.redis_client:
            logger.error(
                "Redis client is not initialized; cannot enqueue learning task for %s",
                response.url,
            )
            return

        try:
            self.redis_client.lpush("discovery_learning_tasks", json.dumps(payload))
            logger.info("Pushed discovery learning task for domain %s", domain)
        except Exception as e:
            logger.error("Failed to push discovery learning task: %s", e)

    def parse_job(self, response: scrapy.http.Response) -> Iterator[RawJobItem]:
        """Extract job details and HTML content."""
        logger.info(f"Parsing job: {response.url}")

        # Extract relevant HTML section
        html_content = response.text

        # Extract metadata if available
        # title = response.css('h1.job-title::text').get()

        item = self.create_item(
            url=response.url,
            html=html_content,
            # title=title,  # Additional metadata
        )

        yield item
