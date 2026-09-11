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
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import redis
import scrapy
from scrapy.crawler import Crawler

from adapters.adapters.base import strip_filter_params
from adapters.registry import AdapterRegistry
from scraper.database import SessionLocal
from scraper.items import RawJobItem
from scraper.models import START_URL_TYPE_API, START_URL_TYPE_HTML_CRAWL, StartUrl
from scraper.spiders.base_spider import BaseJobSpider
from scraper.spiders.posting_filters import apply_filters

logger = logging.getLogger(__name__)


class DiscoverySpider(BaseJobSpider):
    """Generic spider: resolves a discovery adapter by URL netloc and enqueues
    a learning task when none is registered yet.
    """

    name = "google"

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

    @classmethod
    def load_start_urls(cls, session) -> list[tuple[uuid.UUID | None, str, str]]:
        """Return (start_url_id, url, type) triples to crawl, ordered by name.

        Reads `html_crawl` and `api` rows that are `active`. An empty table and a
        table holding only inactive rows are the same situation from an operator's
        side, namely that the table is not driving this crawl, so both are
        covered by the one warning below rather than a separate one per case.
        """
        rows = (
            session.query(StartUrl)
            .filter(
                StartUrl.type.in_([START_URL_TYPE_HTML_CRAWL, START_URL_TYPE_API]),
                StartUrl.active,
            )
            .order_by(StartUrl.name)
            .all()
        )
        if not rows:
            total_count = session.query(StartUrl).count()
            logger.warning(
                "This crawl has nothing to do: no start_urls row is both type"
                " %r or %r and active, out of %d configured.",
                START_URL_TYPE_HTML_CRAWL,
                START_URL_TYPE_API,
                total_count,
            )
        return [(row.id, row.url, row.type) for row in rows]

    def start_requests(self) -> Iterator[scrapy.Request]:
        """Yield one request per configured start URL, tagged with its row id."""
        session = SessionLocal()
        try:
            rows = self.load_start_urls(session)
        finally:
            session.close()

        for start_url_id, url, start_url_type in rows:
            if start_url_type == START_URL_TYPE_API:
                yield scrapy.Request(
                    strip_filter_params(url),
                    callback=self.parse_api,
                    meta={"start_url_id": start_url_id, "stored_url": url},
                )
            else:
                yield scrapy.Request(
                    url, callback=self.parse, meta={"start_url_id": start_url_id}
                )

    def parse(self, response: scrapy.http.Response) -> Iterator[scrapy.Request]:
        """Extract job links from search results page."""
        logger.info(f"Parsing search page: {response.url}")

        start_url_id: uuid.UUID | None = response.meta.get("start_url_id")
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
                yield response.follow(
                    link,
                    callback=self.parse_job,
                    meta={"start_url_id": start_url_id},
                )

            # 2. Next Page
            next_links = adapter.get_next_page_links(response.text, response.url)
            if next_links:  # might be None or []
                for link in next_links:
                    yield response.follow(
                        link, callback=self.parse, meta={"start_url_id": start_url_id}
                    )
        except Exception as e:
            logger.error(f"Adapter logic failed on index page {response.url}: {e}")
            self._trigger_discovery_learning(response)

    def _trigger_discovery_learning(self, response: scrapy.http.Response):
        """Push listing HTML to discovery_learning_tasks queue.

        Payload schema (consumed by LLM worker):
          domain    - netloc extracted from the URL (required for deduplication lock)
          url       - full URL for context
          html      - raw page HTML
          timestamp - ISO-8601 string
        """
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

    def parse_api(
        self, response: scrapy.http.Response
    ) -> Iterator[scrapy.Request | RawJobItem]:
        """Turn an ``api`` board's response into filtered postings.

        Every refusal below logs at error, yields nothing at all from the
        response, and raises nothing out of this callback.
        """
        stored_url: str = response.meta["stored_url"]
        start_url_id = response.meta.get("start_url_id")
        hostname = urlsplit(response.url).hostname

        try:
            # The bytes, never response.text: JSON is UTF-8 by specification,
            # so decoding by the header's declared charset can silently mangle it.
            document = json.loads(response.body)
        except ValueError as exc:
            logger.error("Body from %s did not parse as JSON: %s", hostname, exc)
            return
        if not isinstance(document, (dict, list)):
            logger.error(
                "Body from %s parsed to a JSON %s, not an object or array",
                hostname,
                type(document).__name__,
            )
            return

        bare_media_type = self._bare_media_type(response.headers.get("Content-Type"))
        if bare_media_type != "application/json":
            logger.info(
                "Parsed a JSON body from %s despite Content-Type %r",
                response.url,
                bare_media_type,
            )

        mapping = self.registry.get_index_mapping(response.url)
        if mapping is None:
            logger.error("No index mapping registered for %s", hostname)
            return

        refs = mapping.references(document, response.url)
        kept_ids = apply_filters(refs, stored_url, hostname)
        if kept_ids is None:
            return

        for ref in refs:
            if ref.document is None:
                yield response.follow(
                    ref.url,
                    callback=self.parse_job,
                    meta={"start_url_id": start_url_id},
                )
            elif id(ref) in kept_ids:
                yield self.create_item(
                    url=ref.url,
                    content=json.dumps(ref.document, ensure_ascii=False),
                    start_url_id=start_url_id,
                    source_url=response.url,
                    content_type="application/json",
                )

    def parse_job(self, response: scrapy.http.Response) -> Iterator[RawJobItem]:
        """Extract job details and content."""
        logger.info(f"Parsing job: {response.url}")

        # Extract relevant HTML section
        html_content = response.text

        # Extract metadata if available
        # title = response.css('h1.job-title::text').get()

        item = self.create_item(
            url=response.url,
            content=html_content,
            start_url_id=response.meta.get("start_url_id"),
            source_url=response.url,
            content_type=self._bare_media_type(response.headers.get("Content-Type")),
            # title=title,  # Additional metadata
        )

        yield item

    @staticmethod
    def _bare_media_type(content_type_header: bytes | None) -> str:
        """Strip a response's Content-Type header to its media type, lowercased.

        A server sends `text/html; charset=utf-8` far more often than not.
        content_type is a downstream dispatch key compared against a lowercase
        literal, so it drops the parameters rather than storing them verbatim.
        """
        if not content_type_header:
            return "text/html"
        media_type, _, _params = content_type_header.decode().partition(";")
        return media_type.strip().lower()
