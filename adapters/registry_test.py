import unittest

from adapters.adapters.google_discovery_v1 import GoogleDiscoveryAdapter
from adapters.adapters.greenhouse_discovery_v1 import GreenhouseIOAdapter
from adapters.adapters.www_google_com_extraction_v1 import WwwGoogleComExtractionAdapter
from adapters.registry import AdapterRegistry


class TestAdapterRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = AdapterRegistry()

    def test_google_discovery_adapter(self):
        adapter = self.registry.get_discovery_adapter("https://www.google.com/jobs")
        self.assertIsInstance(adapter, GoogleDiscoveryAdapter)

    def test_google_extraction_adapter_is_auto_discovered(self):
        # The learned adapter reaches the registry by its file being dropped into
        # adapters/adapters, so finding it proves discovery needs no registry edit.
        adapter = self.registry.get_extraction_adapter("https://www.google.com/jobs")
        self.assertIsInstance(adapter, WwwGoogleComExtractionAdapter)

    def test_google_domain_without_www(self):
        adapter = self.registry.get_discovery_adapter("https://google.com/careers")
        self.assertIsInstance(adapter, GoogleDiscoveryAdapter)

    def test_greenhouse_discovery_adapter(self):
        adapter = self.registry.get_discovery_adapter(
            "https://job-boards.greenhouse.io/anthropic"
        )
        self.assertIsInstance(adapter, GreenhouseIOAdapter)

    def test_greenhouse_domain_root(self):
        adapter = self.registry.get_discovery_adapter("https://greenhouse.io/")
        self.assertIsInstance(adapter, GreenhouseIOAdapter)

    def test_no_scheme_url(self):
        adapter = self.registry.get_discovery_adapter("www.google.com/search")
        self.assertIsInstance(adapter, GoogleDiscoveryAdapter)

    def test_domain_lookup_ignores_port(self):
        # A non-default port in netloc must not prevent the host from matching.
        self.registry.register("ported.io", GoogleDiscoveryAdapter)
        adapter = self.registry.get_discovery_adapter("https://ported.io:8443/jobs")
        self.assertIsInstance(adapter, GoogleDiscoveryAdapter)

    def test_unregistered_domain_returns_none(self):
        self.assertIsNone(
            self.registry.get_discovery_adapter("https://www.example.com")
        )
        self.assertIsNone(
            self.registry.get_extraction_adapter("https://www.example.com")
        )

    def test_invalid_url_does_not_crash(self):
        self.assertIsNone(self.registry.get_discovery_adapter("not a url at all"))
        self.assertIsNone(self.registry.get_extraction_adapter("not a url at all"))

    def test_has_discovery_adapter(self):
        self.assertTrue(
            self.registry.has_discovery_adapter("https://www.google.com/jobs")
        )
        self.assertFalse(self.registry.has_discovery_adapter("https://unknown.io"))

    def test_has_extraction_adapter(self):
        # A domain with no adapter is reported unsupported, which is what makes the
        # silver worker enqueue a learning task for it.
        self.assertTrue(
            self.registry.has_extraction_adapter("https://www.google.com/jobs")
        )
        self.assertFalse(self.registry.has_extraction_adapter("https://unknown.io"))

    def test_manual_register_discovery(self):
        self.registry.register("custom.io", GoogleDiscoveryAdapter)
        adapter = self.registry.get_discovery_adapter("https://custom.io/jobs")
        self.assertIsInstance(adapter, GoogleDiscoveryAdapter)

    def test_colliding_domain_warns_and_last_wins(self):
        self.registry.register("collide.io", GoogleDiscoveryAdapter)
        with self.assertLogs("adapters.registry", level="WARNING") as logs:
            self.registry.register("collide.io", GreenhouseIOAdapter)
        self.assertIn("collide.io", "\n".join(logs.output))
        adapter = self.registry.get_discovery_adapter("https://collide.io/jobs")
        self.assertIsInstance(adapter, GreenhouseIOAdapter)

    def test_re_registering_the_same_class_is_silent(self):
        self.registry.register("quiet.io", GoogleDiscoveryAdapter)
        with self.assertNoLogs("adapters.registry", level="WARNING"):
            self.registry.register("quiet.io", GoogleDiscoveryAdapter)


if __name__ == "__main__":
    unittest.main()
