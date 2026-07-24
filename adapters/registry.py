import importlib
import inspect
import logging
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse

from adapters.adapters.base import DiscoveryAdapter, ExtractionAdapter

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Registry that auto-discovers adapters at construction time.

    Each adapter class declares its target domains via a ``domains`` class attribute,
    e.g. ``domains = ["example.com", "www.example.com"]``.  The registry scans every
    non-test, non-base ``.py`` file in the adapters sub-package, imports it, and
    registers any class that inherits from DiscoveryAdapter or ExtractionAdapter.
    """

    def __init__(self) -> None:
        self._discovery_registry: dict[str, type[DiscoveryAdapter]] = {}
        self._extraction_registry: dict[str, type[ExtractionAdapter]] = {}
        self._auto_discover()

    def register(
        self,
        domain: str,
        adapter_cls: Union[type[DiscoveryAdapter], type[ExtractionAdapter]],
    ) -> None:
        """Explicitly register an adapter class for a domain."""
        if issubclass(adapter_cls, DiscoveryAdapter):
            logger.debug(
                "Registering discovery adapter %s for %s", adapter_cls.__name__, domain
            )
            self._warn_on_collision(self._discovery_registry, domain, adapter_cls)
            self._discovery_registry[domain] = adapter_cls
        if issubclass(adapter_cls, ExtractionAdapter):
            logger.debug(
                "Registering extraction adapter %s for %s", adapter_cls.__name__, domain
            )
            self._warn_on_collision(self._extraction_registry, domain, adapter_cls)
            self._extraction_registry[domain] = adapter_cls

    @staticmethod
    def _warn_on_collision(registry: dict, domain: str, adapter_cls: type) -> None:
        """Surface a same-domain overwrite; _auto_discover order decides the winner.

        Two adapters claiming one domain (a generated ``google_com_extraction_v1``
        next to a hand-written ``google_extraction_v1``) otherwise resolve silently by
        lexicographic filename order, masking one and re-triggering its learning.
        """
        existing = registry.get(domain)
        if existing is not None and existing is not adapter_cls:
            logger.warning(
                "Domain %r already maps to %s; overriding with %s. Rename or remove "
                "one — selection otherwise depends on module load order.",
                domain,
                existing.__name__,
                adapter_cls.__name__,
            )

    def get_discovery_adapter(self, url: str) -> Optional[DiscoveryAdapter]:
        """Return an instantiated discovery adapter for *url*, or None."""
        domain = self._domain_from_url(url)
        cls = self._discovery_registry.get(domain) if domain else None
        return cls() if cls else None

    def get_extraction_adapter(self, url: str) -> Optional[ExtractionAdapter]:
        """Return an instantiated extraction adapter for *url*, or None."""
        domain = self._domain_from_url(url)
        cls = self._extraction_registry.get(domain) if domain else None
        return cls() if cls else None

    def has_discovery_adapter(self, url: str) -> bool:
        domain = self._domain_from_url(url)
        return bool(domain and domain in self._discovery_registry)

    def has_extraction_adapter(self, url: str) -> bool:
        domain = self._domain_from_url(url)
        return bool(domain and domain in self._extraction_registry)

    def _auto_discover(self) -> None:
        """Scan adapters and register every class with a non-empty ``domains``."""
        adapters_dir = Path(__file__).parent / "adapters"
        if not adapters_dir.is_dir():
            logger.warning("Adapters sub-directory not found: %s", adapters_dir)
            return

        _SKIP = {"base", "base_test"}

        for module_file in sorted(adapters_dir.glob("*.py")):
            stem = module_file.stem
            if stem.startswith("_") or stem.endswith("_test") or stem in _SKIP:
                continue

            module_name = f"adapters.adapters.{stem}"
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                logger.error("Failed to import adapter module %s: %s", module_name, exc)
                continue

            for _, cls in inspect.getmembers(module, inspect.isclass):
                # Only register classes defined in this module (not re-imports)
                if cls.__module__ != module_name:
                    continue
                if not issubclass(cls, (DiscoveryAdapter, ExtractionAdapter)):
                    continue
                if cls in (DiscoveryAdapter, ExtractionAdapter):
                    continue

                declared_domains: list[str] = getattr(cls, "domains", [])
                if not declared_domains:
                    logger.warning(
                        "Adapter class %s in %s has no declared domains — skipping",
                        cls.__name__,
                        module_name,
                    )
                    continue

                for domain in declared_domains:
                    self.register(domain, cls)

    @staticmethod
    def _domain_from_url(url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            domain = parsed.hostname
            if not domain and parsed.path:
                domain = parsed.path.split("/")[0]
            return domain or None
        except Exception as exc:
            logger.error("Error parsing URL %s: %s", url, exc)
            return None
