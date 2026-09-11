import json
import tempfile
import unittest
from pathlib import Path

from adapters.adapters.base import DetailMapping, IndexMapping
from adapters.adapters.google_discovery_v1 import GoogleDiscoveryAdapter
from adapters.adapters.greenhouse_discovery_v1 import GreenhouseIOAdapter
from adapters.adapters.mapping import MappedIndex
from adapters.adapters.www_google_com_extraction_v1 import WwwGoogleComExtractionAdapter
from adapters.registry import AdapterRegistry


class _StubIndexMapping(IndexMapping):
    """A hand-written escape-hatch mapping, for exercising manual registration."""

    domains = ["stub-index.example.com"]

    def fetch_url(self, start_url: str) -> str:
        return start_url

    def references(self, document: dict, start_url: str) -> list:
        return []


class _StubDetailMapping(DetailMapping):
    domains = ["stub-detail.example.com"]

    def to_silver(self, document: dict) -> dict:
        return {}


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

    def test_manual_register_index_mapping(self):
        self.registry.register("custom-index.io", _StubIndexMapping)
        mapping = self.registry.get_index_mapping("https://custom-index.io/jobs")
        self.assertIsInstance(mapping, _StubIndexMapping)

    def test_manual_register_detail_mapping(self):
        self.registry.register("custom-detail.io", _StubDetailMapping)
        mapping = self.registry.get_detail_mapping("https://custom-detail.io/jobs")
        self.assertIsInstance(mapping, _StubDetailMapping)

    def test_unregistered_domain_has_no_mapping(self):
        self.assertIsNone(self.registry.get_index_mapping("https://www.example.com"))
        self.assertIsNone(self.registry.get_detail_mapping("https://www.example.com"))


class MappingDocumentDiscoveryTest(unittest.TestCase):
    """A mapping document is registered from a directory the test itself wrote.

    ``adapters/adapters/mappings/`` ships empty, so nothing here relies on a
    committed document.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        document = {
            "version": 1,
            "domains": ["mapped-a.example.com", "mapped-b.example.com"],
            "jmespath": {"postings": "jobs[]", "job_url": "url"},
        }
        (Path(self._tmp.name) / "mapped_index_v1.json").write_text(json.dumps(document))
        self.registry = AdapterRegistry(mappings_dir=Path(self._tmp.name))

    def test_mapping_is_served_for_each_declared_domain(self):
        for domain in ("mapped-a.example.com", "mapped-b.example.com"):
            mapping = self.registry.get_index_mapping(f"https://{domain}/jobs")
            self.assertIsInstance(mapping, MappedIndex)

    def test_mapping_is_not_returned_as_a_discovery_or_extraction_adapter(self):
        url = "https://mapped-a.example.com/jobs"
        self.assertIsNone(self.registry.get_discovery_adapter(url))
        self.assertIsNone(self.registry.get_extraction_adapter(url))


if __name__ == "__main__":
    unittest.main()
