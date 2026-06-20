from abc import ABC, abstractmethod

from adapters.adapters.base import DiscoveryAdapter, ExtractionAdapter


class BaseDiscoveryAdapterTest(ABC):
    """Base test suite for DiscoveryAdapters.

    Serves as an implementation hint for what needs to be tested
    for automatically learned discovery adapters.
    """

    @abstractmethod
    def get_adapter(self) -> DiscoveryAdapter:
        """Return the adapter instance to test."""
        pass

    @abstractmethod
    def get_html_with_jobs(self) -> str:
        """Return HTML content containing job listings."""
        pass

    @abstractmethod
    def get_html_without_jobs(self) -> str:
        """Return HTML content with no job listings."""
        pass

    @abstractmethod
    def get_html_with_next_page(self) -> str:
        """Return HTML content with a next page link."""
        pass

    @abstractmethod
    def get_html_without_next_page(self) -> str:
        """Return HTML content with no next page link."""
        pass

    def test_get_job_links_returns_links(self):
        adapter = self.get_adapter()
        html = self.get_html_with_jobs()
        links = adapter.get_job_links(html, "https://example.com/jobs")
        self.assertGreater(len(links), 0, "Should find at least one job link")
        self.assertTrue(
            all(isinstance(link, str) for link in links),
            "All returned links must be strings",
        )

    def test_get_job_links_empty(self):
        adapter = self.get_adapter()
        html = self.get_html_without_jobs()
        links = adapter.get_job_links(html, "https://example.com/jobs")
        self.assertEqual(len(links), 0, "Should return empty list when no jobs exist")

    def test_get_next_page_links_returns_links(self):
        adapter = self.get_adapter()
        html = self.get_html_with_next_page()
        links = adapter.get_next_page_links(html, "https://example.com/jobs")
        self.assertGreater(len(links), 0, "Should find next page link")
        self.assertTrue(
            all(isinstance(link, str) for link in links),
            "All next page links must be strings",
        )

    def test_get_next_page_links_empty(self):
        adapter = self.get_adapter()
        html = self.get_html_without_next_page()
        links = adapter.get_next_page_links(html, "https://example.com/jobs")
        self.assertEqual(
            len(links), 0, "Should return empty list when no next page exists"
        )


class BaseExtractionAdapterTest(ABC):
    """Base test suite for ExtractionAdapters.

    Serves as an implementation hint for what needs to be tested
    for automatically learned extraction adapters.
    """

    @abstractmethod
    def get_adapter(self) -> ExtractionAdapter:
        """Return the adapter instance to test."""
        pass

    @abstractmethod
    def get_job_html(self) -> str:
        """Return HTML content for a single job posting."""
        pass

    def test_extract_returns_expected_data(self):
        adapter = self.get_adapter()
        html = self.get_job_html()
        data = adapter.extract(html, "https://example.com/job/123")
        self.assertIsInstance(data, dict, "Extract must return a dictionary")
