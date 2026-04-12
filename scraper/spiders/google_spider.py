"""Example Indeed spider (template for implementation).

This is a placeholder spider showing the structure.
Actual implementation will require:
1. Analyzing Indeed's HTML structure
2. Handling pagination
3. Extracting job links
4. Handling rate limiting / anti-bot measures
"""

import logging
from collections.abc import Iterator

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

    def parse(self, response: scrapy.http.Response) -> Iterator[scrapy.Request]:
        """Extract job links from search results page."""
        logger.info(f"Parsing search page: {response.url}")

        registry = AdapterRegistry()
        adapter = registry.get_adapter_for_url(response.url)

        # If no adapter, log fallback and STOP spidering for this domain/url path
        if not adapter:
            logger.warning(
                f"No adapter found for domain parsing jobs: {response.url}. "
                "Triggering learning pipeline logic will not happen correctly without an adapter."
            )
            # You could theoretically emit a 'RAW_HTML' learning task from here for the INDEX page
            # but Sliver Worker focuses on the JOB detail page for extraction usually
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
