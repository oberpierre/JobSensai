"""The mapping engine: interprets a parsing rule expressed as a JMESPath document.

A document declares `version` (must be 1), a non-empty `domains` list and a
`jmespath` block of one expression string per key: `postings` and `job_url` for an
index document, a subset of the Silver schema for a detail one. Every expression is
compiled once at construction, so a typo in a document fails loudly there rather
than the first time a posting reaches it.
"""

import html
import json
import logging
from pathlib import Path
from typing import Any

import jmespath
from jmespath import functions

from adapters.adapters._markdown import html_to_markdown
from adapters.adapters.base import DetailMapping, IndexMapping, PostingRef

logger = logging.getLogger(__name__)

# The Silver schema jmespath keys a detail document may declare, matching what
# ExtractionAdapter.extract() returns.
_SILVER_SCHEMA_KEYS = frozenset(
    {
        "title",
        "company_name",
        "employment_type",
        "locations",
        "categories",
        "description",
        "metadata",
    }
)

# The two jmespath keys an index document may declare.
_INDEX_JMESPATH_KEYS = frozenset({"postings", "job_url"})

_TOP_LEVEL_KEYS = frozenset({"version", "domains", "jmespath"})

_SUPPORTED_VERSION = 1


class MappingError(ValueError):
    """A mapping document failed construction-time validation."""


class _MappingFunctions(functions.Functions):
    """The two custom JMESPath functions a mapping document may call.

    Each is typed to a single string argument so a mapping applying it to a list
    raises at map time (a JMESPath type error) rather than silently stringifying it.
    """

    @functions.signature({"types": ["string", "null"]})
    def _func_unescape(self, value: str | None) -> str | None:
        # An absent source key evaluates to None quietly, like any other path.
        # A genuine type mismatch (a list, say) is the loud case this signature guards.
        return html.unescape(value) if value is not None else None

    @functions.signature({"types": ["string", "null"]})
    def _func_markdown(self, value: str | None) -> str | None:
        return html_to_markdown(value) if value is not None else None


_CUSTOM_FUNCTION_NAMES = frozenset({"unescape", "markdown"})
_BUILTIN_FUNCTION_NAMES = frozenset(functions.Functions.FUNCTION_TABLE.keys())
_KNOWN_FUNCTION_NAMES = _BUILTIN_FUNCTION_NAMES | _CUSTOM_FUNCTION_NAMES
_OPTIONS = jmespath.Options(custom_functions=_MappingFunctions())


def _assert_disjoint_vocabularies(
    silver_keys: frozenset, index_keys: frozenset
) -> None:
    """Guard the assumption ``load_mapping`` classifies a document by key vocabulary.

    That classification holds only while the two vocabularies never share a key,
    because a Silver field named e.g. ``postings`` would otherwise silently
    misclassify every index document.
    """
    overlap = silver_keys & index_keys
    assert not overlap, f"index and Silver vocabularies overlap: {sorted(overlap)}"


_assert_disjoint_vocabularies(_SILVER_SCHEMA_KEYS, _INDEX_JMESPATH_KEYS)


def _validate_function_names(node: Any) -> None:
    """Walk a compiled expression's parsed tree, refusing any unknown function call.

    ``jmespath.compile`` does not check function names on its own, those resolving
    only during evaluation, so an unknown name would otherwise surface at the first
    posting mapped rather than here.
    """
    if not isinstance(node, dict):
        return
    if node.get("type") == "function_expression":
        name = node.get("value")
        if name not in _KNOWN_FUNCTION_NAMES:
            raise MappingError(f"unknown function: {name!r}")
    for child in node.get("children", []):
        _validate_function_names(child)


def _validate_top_level(document: dict) -> None:
    unknown = set(document) - _TOP_LEVEL_KEYS
    if unknown:
        raise MappingError(f"unknown top-level key(s): {sorted(unknown)}")


def _validate_version(document: dict) -> None:
    if document.get("version") != _SUPPORTED_VERSION:
        raise MappingError(f"unsupported version: {document.get('version')!r}")


def _validate_domains(document: dict) -> list[str]:
    domains = document.get("domains")
    if (
        not isinstance(domains, list)
        or not domains
        or not all(isinstance(entry, str) for entry in domains)
    ):
        raise MappingError("'domains' must be a non-empty list of strings")
    return list(domains)


def _compile_jmespath_block(document: dict, allowed_keys: frozenset) -> dict:
    block = document.get("jmespath")
    if not isinstance(block, dict):
        raise MappingError("'jmespath' must be an object")
    if not block:
        raise MappingError("'jmespath' must not be empty")
    compiled = {}
    for key, expression in block.items():
        if key not in allowed_keys:
            raise MappingError(f"unknown jmespath key: {key!r}")
        try:
            parsed = jmespath.compile(expression)
        except jmespath.exceptions.ParseError as exc:
            raise MappingError(
                f"invalid jmespath expression for {key!r}: {exc}"
            ) from exc
        except TypeError as exc:
            raise MappingError(
                f"jmespath expression for {key!r} must be a string: {exc}"
            ) from exc
        _validate_function_names(parsed.parsed)
        compiled[key] = parsed
    return compiled


class MappedIndex(IndexMapping):
    """An index mapping interpreted from a document: finds postings and their URLs."""

    def __init__(self, document: dict) -> None:
        _validate_top_level(document)
        _validate_version(document)
        self.domains: list[str] = _validate_domains(document)
        self._compiled = _compile_jmespath_block(document, _INDEX_JMESPATH_KEYS)
        missing = _INDEX_JMESPATH_KEYS - self._compiled.keys()
        if missing:
            raise MappingError(f"index document missing key(s): {sorted(missing)}")

    def references(self, document: dict, start_url: str) -> list[PostingRef]:
        postings = self._compiled["postings"].search(document, options=_OPTIONS)
        if not isinstance(postings, list):
            logger.error(
                "postings expression for %s resolved to %s, not a list",
                start_url,
                type(postings).__name__,
            )
            return []
        job_url_expr = self._compiled["job_url"]
        refs = []
        for element in postings:
            url = job_url_expr.search(element, options=_OPTIONS)
            if url is None:
                logger.error(
                    "job_url expression resolved to no identity for a posting from %s",
                    start_url,
                )
                continue
            refs.append(PostingRef(url=url, document=element))
        return refs


class MappedDetail(DetailMapping):
    """A detail mapping interpreted from a document: reads a posting into Silver."""

    def __init__(self, document: dict) -> None:
        _validate_top_level(document)
        _validate_version(document)
        self.domains: list[str] = _validate_domains(document)
        self._compiled = _compile_jmespath_block(document, _SILVER_SCHEMA_KEYS)

    def to_silver(self, document: dict) -> dict:
        return {
            key: expr.search(document, options=_OPTIONS)
            for key, expr in self._compiled.items()
        }


def load_mapping(document: dict) -> IndexMapping | DetailMapping:
    """Build the mapping *document* describes, classified by its own ``jmespath`` keys.

    An index document's keys are a subset of ``{postings, job_url}``, whereas a
    detail document's are a subset of the Silver schema. The two vocabularies are
    disjoint, so a well-formed document is unambiguous.
    """
    _validate_top_level(document)
    block = document.get("jmespath")
    if not isinstance(block, dict):
        raise MappingError("'jmespath' must be an object")
    keys = set(block)
    if keys <= _INDEX_JMESPATH_KEYS:
        return MappedIndex(document)
    if keys <= _SILVER_SCHEMA_KEYS:
        return MappedDetail(document)
    index_keys = sorted(keys & _INDEX_JMESPATH_KEYS)
    detail_keys = sorted(keys & _SILVER_SCHEMA_KEYS)
    if index_keys and detail_keys:
        raise MappingError(
            f"document mixes index key(s) {index_keys} and detail key(s) {detail_keys}"
        )
    unknown = sorted(keys - _SILVER_SCHEMA_KEYS - _INDEX_JMESPATH_KEYS)
    raise MappingError(f"unknown jmespath key(s): {unknown}")


def load_mapping_file(path: Path) -> IndexMapping | DetailMapping:
    """``json.load`` *path* and build the mapping it describes."""
    return load_mapping(json.loads(path.read_text()))
