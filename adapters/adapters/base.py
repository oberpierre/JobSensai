from abc import ABC, abstractmethod
from dataclasses import dataclass

from adapters.adapters import filters


class DiscoveryAdapter(ABC):
    """Abstract base class for job discovery (finding links)."""

    # Declare the domains handled, e.g. ["example.com", "www.example.com"].
    domains: list[str] = []

    @abstractmethod
    def get_job_links(self, html: str, url: str) -> list[str]:
        """Extracts job posting URLs from a job board listing page.

        Args:
            html: The raw HTML content of the listing page.
            url: The URL of the listing page (for resolving relative links).

        Returns:
            A list of absolute URLs for job postings.
        """
        pass

    @abstractmethod
    def get_next_page_links(self, html: str, url: str) -> list[str]:
        """Extracts pagination URLs from a job board listing page.

        Args:
            html: The raw HTML content of the listing page.
            url: The URL of the listing page.

        Returns:
            A list of absolute URLs for the next pages.
        """
        pass

    @property
    def version(self) -> int:
        """Returns the version of this adapter."""
        return 1


@dataclass(frozen=True)
class PostingRef:
    """One posting the index stage found."""

    url: str  # canonical URL, and the posting's identity in Bronze
    document: dict | list | None  # the posting in hand, or None when it must be fetched


class IndexMapping(ABC):
    """Finds postings in an API response and the URL each one is identified by.

    Declares ``domains`` like DiscoveryAdapter/ExtractionAdapter for the Python escape
    hatch. A document-driven mapping (``adapters/adapters/mapping.py::MappedIndex``)
    carries its ``domains`` per instance instead.
    """

    domains: list[str] = []

    def fetch_url(self, start_url: str) -> str:
        """Return *start_url* with every ``filter.``-prefixed parameter removed.

        Concrete rather than abstract: the spider needs this before it has looked up
        a mapping, and an abstract method would make every escape-hatch mapping
        responsible for remembering the convention on its own.
        """
        return filters.strip_filter_params(start_url)

    @abstractmethod
    def references(self, document: dict | list, start_url: str) -> list[PostingRef]:
        """Return the postings *document* (the response to *start_url*) carries."""
        pass


class DetailMapping(ABC):
    """Reads one posting document into the Silver schema."""

    domains: list[str] = []

    @abstractmethod
    def to_silver(self, document: dict | list) -> dict:
        """Return the Silver fields *document* (one posting) carries."""
        pass


class ExtractionAdapter(ABC):
    """Abstract base class for job data extraction."""

    # declares the domains handled, e.g. ["example.com", "www.example.com"].
    domains: list[str] = []

    @abstractmethod
    def extract(self, html: str, url: str) -> dict:
        """Extracts structured job data from a job detail page.

        Args:
            html: The raw HTML content of the job detail page.
            url: The URL of the job posting.

        Returns:
            A dictionary containing the extracted job data (Silver Schema).
        """
        pass

    @property
    def version(self) -> int:
        """Returns the version of this adapter."""
        return 1
