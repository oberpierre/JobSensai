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
from urllib.parse import parse_qs as urlparseqs
from urllib.parse import urlencode, urlsplit, urlunsplit

import scrapy

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

    def _is_overview_page(self, url: str) -> bool:
        """Determine if URL corresponds to a job overview page."""

        path = urlsplit(url)[2]

        return path.endswith("/jobs/results")

    def next_page_url(self, url: str) -> str:
        """Generate URL for the next page of results."""
        # urlsplit returns a 5-tuple: (scheme, netloc, path, query, fragment)
        urlparts = urlsplit(url)
        qs = urlparseqs(qs=urlparts[3])
        page = int(qs["page"][0]) if "page" in qs else 1
        qs["page"] = [str(page + 1)]
        return urlunsplit(
            [
                urlparts[0],
                urlparts[1],
                urlparts[2],
                urlencode(qs, doseq=True),
                urlparts[4],
            ]
        )

    def parse(self, response: scrapy.http.Response) -> Iterator[scrapy.Request]:
        """Extract job links from search results page."""
        logger.info(f"Parsing search page: {response.url}")

        for listing in response.css("a[jsname='hSRGPd']"):
            if listing.attrib["aria-label"].startswith("Learn more"):
                yield response.follow(listing.attrib["href"], callback=self.parse_job)
            elif listing.attrib["aria-label"].startswith("Go to next page"):
                yield response.follow(
                    self.next_page_url(response.url), callback=self.parse
                )

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
