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
    - parse_job(): Extract the posting's content from individual job postings
    """

    name = "base_job_spider"

    def create_item(
        self,
        url: str,
        content: str,
        *,
        start_url_id: uuid.UUID | None = None,
        source_url: str,
        content_type: str,
        **metadata: Any,
    ) -> RawJobItem:
        """Create a RawJobItem with common metadata.

        Args:
            url: Job posting URL
            content: Raw content fetched for the posting
            start_url_id: id of the start_urls row whose crawl discovered this page
            source_url: URL actually fetched, which for an API posting is the feed
                rather than the posting's own url
            content_type: bare media type that content holds, e.g. text/html
            **metadata: Additional metadata fields

        Returns:
            RawJobItem ready for pipeline processing
        """
        item = RawJobItem()
        item["url"] = url
        item["raw_content"] = content
        item["start_url_id"] = str(start_url_id) if start_url_id is not None else None
        item["source_url"] = source_url
        item["content_type"] = content_type
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
        """Parse individual job posting page and extract its content.

        Should yield RawJobItem with URL and the posting's content.
        """
        pass
