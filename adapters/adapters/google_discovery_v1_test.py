import unittest

from adapters.adapters.base_test import BaseDiscoveryAdapterTest
from adapters.adapters.google_discovery_v1 import GoogleDiscoveryAdapter


class TestGoogleDiscoveryAdapter(BaseDiscoveryAdapterTest, unittest.TestCase):
    """Test suite for the Google Careers discovery adapter.

    This implements the base test suite for discovery adapters.
    """

    def setUp(self):
        self.adapter = GoogleDiscoveryAdapter()

    def get_adapter(self):
        return self.adapter

    def get_html_with_jobs(self) -> str:
        return """
        <html>
            <body>
                <a jsname="hSRGPd" aria-label="Learn more about Software Engineer" href="https://google.com/careers/job1">Job 1</a>
                <a jsname="hSRGPd" aria-label="Learn more about Product Manager" href="https://google.com/careers/job2">Job 2</a>
                <a href="https://other.com">Not a job</a>
            </body>
        </html>
        """  # noqa: E501

    def get_html_without_jobs(self) -> str:
        return """
        <html>
            <body>
                <p>No jobs found.</p>
            </body>
        </html>
        """

    def get_html_with_next_page(self) -> str:
        return """
        <html>
            <body>
                <a jsname="hSRGPd" aria-label="Go to next page" href="#">Next</a>
            </body>
        </html>
        """

    def get_html_without_next_page(self) -> str:
        return """
        <html>
            <body>
                <p>End of results.</p>
            </body>
        </html>
        """

    def test_get_job_links_returns_links(self):
        # Override with specific assertion for Google
        links = self.adapter.get_job_links(
            self.get_html_with_jobs(), "https://example.com/jobs"
        )
        self.assertEqual(len(links), 2)
        self.assertEqual(links[0], "https://google.com/careers/job1")
        self.assertEqual(links[1], "https://google.com/careers/job2")

    def test_get_next_page_links_returns_links(self):
        # Override with specific assertion for Google
        links = self.adapter.get_next_page_links(
            self.get_html_with_next_page(), "https://example.com/jobs?page=1"
        )
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0], "https://example.com/jobs?page=2")
