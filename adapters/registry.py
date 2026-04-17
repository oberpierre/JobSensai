import logging
from typing import Optional, Union
from urllib.parse import urlparse

from adapters.base import BaseAdapter, DiscoveryAdapter, ExtractionAdapter
from adapters.google_v1 import GoogleJobAdapter

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Registry to map domains to their corresponding scraper adapters."""

    def __init__(self):
        # Map domain (e.g., 'google.com') to Adapter class
        self._discovery_registry: dict[str, type[DiscoveryAdapter]] = {}
        self._extraction_registry: dict[str, type[ExtractionAdapter]] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register known adapters."""
        self.register("google.com", GoogleJobAdapter)
        self.register("www.google.com", GoogleJobAdapter)

    def register(
        self,
        domain: str,
        adapter_cls: Union[
            type[DiscoveryAdapter], type[ExtractionAdapter], type[BaseAdapter]
        ],
    ):
        """Register an adapter for a specific domain."""
        logger.info(f"Registering adapter {adapter_cls.__name__} for domain: {domain}")

        is_discovery = issubclass(adapter_cls, DiscoveryAdapter)
        is_extraction = issubclass(adapter_cls, ExtractionAdapter)

        if is_discovery:
            self._discovery_registry[domain] = adapter_cls
        if is_extraction:
            self._extraction_registry[domain] = adapter_cls

    def get_discovery_adapter(self, url: str) -> Optional[DiscoveryAdapter]:
        """Find and instantiate the correct discovery adapter for a given URL."""
        domain = self._get_domain(url)
        if domain and domain in self._discovery_registry:
            return self._discovery_registry[domain]()
        return None

    def get_extraction_adapter(self, url: str) -> Optional[ExtractionAdapter]:
        """Find and instantiate the correct extraction adapter for a given URL."""
        domain = self._get_domain(url)
        if domain and domain in self._extraction_registry:
            return self._extraction_registry[domain]()
        return None

    def get_adapter_for_url(self, url: str) -> Optional[BaseAdapter]:
        """Legacy method to find and instantiate a BaseAdapter (must support both)."""
        domain = self._get_domain(url)
        if (
            domain
            and domain in self._discovery_registry
            and domain in self._extraction_registry
        ):
            # Check if it's the same class or if we can instantiate it as a BaseAdapter
            adapter_cls = self._discovery_registry[domain]
            if issubclass(adapter_cls, BaseAdapter):
                return adapter_cls()
        return None

    def _get_domain(self, url: str) -> Optional[str]:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if not domain and parsed.path:
                domain = parsed.path.split("/")[0]
            return domain
        except Exception as e:
            logger.error(f"Error parsing URL {url}: {e}")
            return None
