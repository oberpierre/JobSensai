from urllib.parse import parse_qs as urlparseqs
from urllib.parse import urlencode, urlsplit, urlunsplit

from parsel import Selector

from adapters.base import DiscoveryAdapter, ExtractionAdapter


class GoogleDiscoveryAdapter(DiscoveryAdapter):
    """Discovery adapter for Google Careers."""

    def get_job_links(self, html: str, url: str) -> list[str]:
        selector = Selector(text=html)
        links = []

        for listing in selector.css("a[jsname='hSRGPd']"):
            aria_label = listing.attrib.get("aria-label", "")
            href = listing.attrib.get("href")

            if aria_label.startswith("Learn more") and href:
                links.append(href)

        return links

    def get_next_page_links(self, html: str, url: str) -> list[str]:
        selector = Selector(text=html)

        for listing in selector.css("a[jsname='hSRGPd']"):
            aria_label = listing.attrib.get("aria-label", "")
            if aria_label.startswith("Go to next page"):
                return [self._generate_next_page_url(url)]
        return []

    def _generate_next_page_url(self, url: str) -> str:
        """Generate URL for the next page of results."""
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


class GoogleExtractionAdapter(ExtractionAdapter):
    """Extraction adapter for Google Careers."""

    def extract(self, html: str, url: str) -> dict:
        # TODO: Implement extraction logic for silver data lake
        return {}
