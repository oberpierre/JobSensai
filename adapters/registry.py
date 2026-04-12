import logging
from typing import Optional
from urllib.parse import urlparse

from adapters.base import BaseAdapter
from adapters.google_v1 import GoogleJobAdapter

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Registry to map domains to their corresponding scraper adapters."""

    def __init__(self):
        # Map domain (e.g., 'google.com') to Adapter class
        self._registry: dict[str, type[BaseAdapter]] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register known adapters."""
        self.register("google.com", GoogleJobAdapter)
        self.register("www.google.com", GoogleJobAdapter)

    def register(self, domain: str, adapter_cls: type[BaseAdapter]):
        """Register an adapter for a specific domain."""
        logger.info(f"Registering adapter {adapter_cls.__name__} for domain: {domain}")
        self._registry[domain] = adapter_cls

    def get_adapter_for_url(self, url: str) -> Optional[BaseAdapter]:
        """Find and instantiate the correct adapter for a given URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc

            # Handle case where URL might not have a scheme
            if not domain and parsed.path:
                # If parsed like 'google.com/jobs',
                # netloc is empty and path is 'google.com/jobs'
                domain = parsed.path.split("/")[0]

            if domain in self._registry:
                return self._registry[domain]()

            logger.warning(f"No adapter found for domain: {domain}")
            return None

        except Exception as e:
            logger.error(f"Error parsing URL {url}: {e}")
            return None
