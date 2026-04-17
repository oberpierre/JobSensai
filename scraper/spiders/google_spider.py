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
from collections.abc import Iterator
from datetime import UTC, datetime

import redis
import scrapy
from adapters.registry import AdapterRegistry

from scraper.items import RawJobItem
from scraper.spiders.base_spider import BaseJobSpider

logger = logging.getLogger(__name__)


class GoogleSpider(BaseJobSpider):
    """Spider for scraping Google job postings."""

    name = "google"

    # TODO: Configure these based on search criteria
    start_urls = [
        "https://www.google.com/about/careers/applications/jobs/results/?location=Switzerland&location=Singapore&sort_by=date",
        # https://www.google.com/about/careers/applications/jobs/results/120830781164528326-program-manager-talent-outreach-talent-engagement?location=Switzerland&location=Singapore&sort_by=date
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.registry = AdapterRegistry()
        self.redis_client = redis.Redis(
            host=kwargs.get("redis_host", "localhost"),
            port=int(kwargs.get("redis_port", 6379)),
            decode_responses=True,
        )

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
        """Push listing HTML to discovery_learning_tasks queue."""
        payload = {
            "url": response.url,
            "html": response.text,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        try:
            self.redis_client.lpush("discovery_learning_tasks", json.dumps(payload))
            logger.info(f"Pushed discovery learning task for {response.url}")
        except Exception as e:
            logger.error(f"Failed to push discovery learning task: {e}")

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
