import unittest

from adapters.google_v1 import GoogleJobAdapter
from adapters.registry import AdapterRegistry


class TestAdapterRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = AdapterRegistry()

    def test_get_adapter_valid_url(self):
        adapter = self.registry.get_adapter_for_url("https://www.google.com/jobs")
        self.assertIsInstance(adapter, GoogleJobAdapter)

        adapter2 = self.registry.get_adapter_for_url("http://google.com/careers")
        self.assertIsInstance(adapter2, GoogleJobAdapter)

    def test_get_adapter_no_scheme(self):
        adapter = self.registry.get_adapter_for_url("www.google.com/search")
        self.assertIsInstance(adapter, GoogleJobAdapter)

    def test_get_adapter_unregistered_domain(self):
        adapter = self.registry.get_adapter_for_url("https://www.example.com")
        self.assertIsNone(adapter)

    def test_get_adapter_invalid_url(self):
        # Even with weird URLs it shouldn't crash, just return None
        adapter = self.registry.get_adapter_for_url("not a url at all")
        self.assertIsNone(adapter)


if __name__ == "__main__":
    unittest.main()
