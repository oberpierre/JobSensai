import unittest

from adapters.common.google import GoogleDiscoveryAdapter, GoogleExtractionAdapter
from adapters.registry import AdapterRegistry


class TestAdapterRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = AdapterRegistry()

    def test_get_discovery_adapter(self):
        adapter = self.registry.get_discovery_adapter("https://www.google.com/jobs")
        self.assertIsInstance(adapter, GoogleDiscoveryAdapter)

    def test_get_extraction_adapter(self):
        adapter = self.registry.get_extraction_adapter("https://www.google.com/jobs")
        self.assertIsInstance(adapter, GoogleExtractionAdapter)

    def test_get_adapter_valid_url(self):
        # google.com registered for both, but legacy method returns None
        adapter = self.registry.get_adapter_for_url("https://www.google.com/jobs")
        self.assertIsNone(adapter)

        adapter2 = self.registry.get_adapter_for_url("http://google.com/careers")
        self.assertIsNone(adapter2)

    def test_get_adapter_no_scheme(self):
        adapter = self.registry.get_discovery_adapter("www.google.com/search")
        self.assertIsInstance(adapter, GoogleDiscoveryAdapter)

    def test_get_adapter_unregistered_domain(self):
        adapter = self.registry.get_adapter_for_url("https://www.example.com")
        self.assertIsNone(adapter)

    def test_get_adapter_invalid_url(self):
        # Even with weird URLs it shouldn't crash, just return None
        adapter = self.registry.get_adapter_for_url("not a url at all")
        self.assertIsNone(adapter)


if __name__ == "__main__":
    unittest.main()
