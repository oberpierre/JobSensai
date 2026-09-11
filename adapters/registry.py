import importlib
import inspect
import logging
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse

from adapters.adapters.base import (
    DetailMapping,
    DiscoveryAdapter,
    ExtractionAdapter,
    IndexMapping,
)
from adapters.adapters.mapping import load_mapping_file

logger = logging.getLogger(__name__)

_ADAPTER_BASES = (DiscoveryAdapter, ExtractionAdapter, IndexMapping, DetailMapping)

_DEFAULT_MAPPINGS_DIR = Path(__file__).parent / "adapters" / "mappings"


class AdapterRegistry:
    """Registry that auto-discovers adapters and mappings at construction time.

    Each adapter class declares its target domains via a ``domains`` class attribute,
    e.g. ``domains = ["example.com", "www.example.com"]``.  The registry scans every
    non-test, non-base ``.py`` file in the adapters sub-package, imports it, and
    registers any class that inherits from DiscoveryAdapter, ExtractionAdapter,
    IndexMapping or DetailMapping. It also loads every mapping document under
    *mappings_dir*, registering each under the domains its own ``domains`` key names.
    """

    def __init__(self, mappings_dir: Optional[Path] = None) -> None:
        self._discovery_registry: dict[str, type[DiscoveryAdapter]] = {}
        self._extraction_registry: dict[str, type[ExtractionAdapter]] = {}
        self._index_registry: dict[str, Union[type[IndexMapping], IndexMapping]] = {}
        self._detail_registry: dict[str, Union[type[DetailMapping], DetailMapping]] = {}
        self._auto_discover()
        self._load_mappings(
            mappings_dir if mappings_dir is not None else _DEFAULT_MAPPINGS_DIR
        )

    def register(
        self,
        domain: str,
        adapter_cls: Union[
            type[DiscoveryAdapter],
            type[ExtractionAdapter],
            type[IndexMapping],
            type[DetailMapping],
        ],
    ) -> None:
        """Explicitly register an adapter or mapping class for a domain."""
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
        if issubclass(adapter_cls, IndexMapping):
            logger.debug(
                "Registering index mapping %s for %s", adapter_cls.__name__, domain
            )
            self._warn_on_collision(self._index_registry, domain, adapter_cls)
            self._index_registry[domain] = adapter_cls
        if issubclass(adapter_cls, DetailMapping):
            logger.debug(
                "Registering detail mapping %s for %s", adapter_cls.__name__, domain
            )
            self._warn_on_collision(self._detail_registry, domain, adapter_cls)
            self._detail_registry[domain] = adapter_cls

    @staticmethod
    def _warn_on_collision(registry: dict, domain: str, entry) -> None:
        """Surface a same-domain overwrite, though discovery order decides the winner.

        Two adapters claiming one domain (a generated ``google_com_extraction_v1``
        next to a hand-written ``google_extraction_v1``) otherwise resolve silently by
        lexicographic filename order, masking one and re-triggering its learning.
        """
        existing = registry.get(domain)
        if existing is not None and existing is not entry:
            logger.warning(
                "Domain %r already maps to %s; overriding with %s. Rename or remove "
                "one — selection otherwise depends on module load order.",
                domain,
                getattr(existing, "__name__", type(existing).__name__),
                getattr(entry, "__name__", type(entry).__name__),
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

    def get_index_mapping(self, url: str) -> Optional[IndexMapping]:
        """Return an index mapping for *url*, or None."""
        domain = self._domain_from_url(url)
        entry = self._index_registry.get(domain) if domain else None
        if entry is None:
            return None
        return entry() if inspect.isclass(entry) else entry

    def get_detail_mapping(self, url: str) -> Optional[DetailMapping]:
        """Return a detail mapping for *url*, or None."""
        domain = self._domain_from_url(url)
        entry = self._detail_registry.get(domain) if domain else None
        if entry is None:
            return None
        return entry() if inspect.isclass(entry) else entry

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
                if not issubclass(cls, _ADAPTER_BASES):
                    continue
                if cls in _ADAPTER_BASES:
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

    def _load_mappings(self, mappings_dir: Path) -> None:
        """Load every mapping document under *mappings_dir*.

        The directory ships empty in this repository, mapping documents arriving one
        at a time through the learning loop's pull requests, so a missing directory
        is not an error.
        """
        if not mappings_dir.is_dir():
            return

        for doc_path in sorted(mappings_dir.glob("*.json")):
            try:
                mapping = load_mapping_file(doc_path)
            except Exception as exc:
                logger.error("Failed to load mapping document %s: %s", doc_path, exc)
                continue

            registry = (
                self._index_registry
                if isinstance(mapping, IndexMapping)
                else self._detail_registry
            )
            for domain in mapping.domains:
                self._warn_on_collision(registry, domain, mapping)
                registry[domain] = mapping

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
