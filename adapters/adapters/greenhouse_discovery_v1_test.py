import unittest

from adapters.adapters.base_test import BaseDiscoveryAdapterTest
from adapters.adapters.greenhouse_discovery_v1 import GreenhouseIOAdapter


class TestGreenhouseIOAdapter(BaseDiscoveryAdapterTest, unittest.TestCase):
    def get_adapter(self):
        return GreenhouseIOAdapter()

    def get_html_with_jobs(self) -> str:
        return """
        <html>
        <body>
            <div class="job-listing">
                <a href="/jobs/123">Software Engineer</a>
                <a href="/jobs/456">Product Manager</a>
            </div>
            <div data-job-url="/jobs/789">Data Scientist</div>
        </body>
        </html>
        """

    def get_html_without_jobs(self) -> str:
        return """
        <html>
        <body>
            <div>No job listings here</div>
        </body>
        </html>
        """

    def get_html_with_next_page(self) -> str:
        return """
        <html>
        <body>
            <div class="pagination">
                <a href="/page/2">Next</a>
                <a href="/page/3">3</a>
            </div>
            <div data-next-page="/page/4">Next Page</div>
        </body>
        </html>
        """

    def get_html_without_next_page(self) -> str:
        return """
        <html>
        <body>
            <div>No pagination here</div>
        </body>
        </html>
        """

    def test_get_job_links_returns_links(self):
        adapter = self.get_adapter()
        html = self.get_html_with_jobs()
        links = adapter.get_job_links(html, "https://job-boards.greenhouse.io")
        self.assertGreater(len(links), 0, "Should find at least one job link")
        self.assertTrue(
            all(isinstance(link, str) for link in links),
            "All returned links must be strings",
        )

    def test_get_job_links_empty(self):
        adapter = self.get_adapter()
        html = self.get_html_without_jobs()
        links = adapter.get_job_links(html, "https://job-boards.greenhouse.io")
        self.assertEqual(len(links), 0, "Should return empty list when no jobs exist")

    def test_get_next_page_links_returns_links(self):
        adapter = self.get_adapter()
        html = self.get_html_with_next_page()
        links = adapter.get_next_page_links(html, "https://job-boards.greenhouse.io")
        self.assertGreater(len(links), 0, "Should find next page link")
        self.assertTrue(
            all(isinstance(link, str) for link in links),
            "All next page links must be strings",
        )

    def test_get_next_page_links_empty(self):
        adapter = self.get_adapter()
        html = self.get_html_without_next_page()
        links = adapter.get_next_page_links(html, "https://job-boards.greenhouse.io")
        self.assertEqual(
            len(links), 0, "Should return empty list when no next page exists"
        )
