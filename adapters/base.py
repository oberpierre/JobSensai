from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    """Abstract base class for all job board adapters."""

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
        """Returns the version of this adapter.

        By default, it parses the version from the class name or module,
        but explicit overrides are preferred.
        """
        return 1
