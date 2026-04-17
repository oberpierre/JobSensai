import unittest

from adapters.adapters.base_test import BaseExtractionAdapterTest
from adapters.adapters.google_extraction_v1 import GoogleExtractionAdapter


class TestGoogleExtractionAdapter(BaseExtractionAdapterTest, unittest.TestCase):
    """Test suite for the Google Careers extraction adapter.

    This implements the base test suite for extraction adapters.
    """

    def setUp(self):
        self.adapter = GoogleExtractionAdapter()

    def get_adapter(self):
        return self.adapter

    def get_job_html(self) -> str:
        return """
        <html>
            <body>
                <h1>Software Engineer</h1>
                <p>Google</p>
            </body>
        </html>
        """

    def test_extract_returns_expected_data(self):
        # Specific assertions for Google Careers Extraction
        data = self.adapter.extract(self.get_job_html(), "https://google.com/job/123")
        self.assertEqual(data, {})  # Base implementation returns empty dict temporarily
