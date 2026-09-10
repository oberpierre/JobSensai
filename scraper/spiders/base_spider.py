"""Base spider class for all job board scrapers."""

import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

import scrapy

from scraper.items import RawJobItem

logger = logging.getLogger(__name__)


class BaseJobSpider(scrapy.Spider, ABC):
    """Abstract base spider for job board scraping.

    Subclasses must implement:
    - parse(): Extract job links from entry pages
    - parse_job(): Extract HTML from individual job postings
    """

    name = "base_job_spider"

    def create_item(
        self,
        url: str,
        html: str,
        *,
        start_url_id: uuid.UUID | None = None,
        source_url: str | None = None,
        content_type: str | None = None,
        **metadata: Any,
    ) -> RawJobItem:
        """Create a RawJobItem with common metadata.

        Args:
            url: Job posting URL
            html: Raw content fetched for the posting
            start_url_id: id of the start_urls row whose crawl discovered this page
            source_url: URL actually fetched, defaulting to url for a crawled posting
            content_type: what html holds, defaulting to text/html
            **metadata: Additional metadata fields

        Returns:
            RawJobItem ready for pipeline processing
        """
        item = RawJobItem()
        item["url"] = url
        item["raw_content"] = html
        item["start_url_id"] = str(start_url_id) if start_url_id is not None else None
        item["source_url"] = source_url if source_url is not None else url
        item["content_type"] = content_type or "text/html"
        item["metadata"] = {
            "spider_name": self.name,
            **metadata,
        }
        return item

    @abstractmethod
    def parse(self, response: scrapy.http.Response) -> Iterator[scrapy.Request]:
        """Parse entry page and extract job posting links.

        Should yield scrapy.Request objects with callback=self.parse_job
        """
        pass

    @abstractmethod
    def parse_job(self, response: scrapy.http.Response) -> Iterator[RawJobItem]:
        """Parse individual job posting page and extract HTML.

        Should yield RawJobItem with URL and HTML content.
        """
        pass
