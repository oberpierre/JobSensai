"""The mapping engine: interprets a parsing rule expressed as a JMESPath document.

A document declares `version` (must be 1), `type` (`index` or `detail`), a non-empty
`domains` list and a `jmespath` block of one expression string per key: `postings` and
`posting_url` for an index document, a subset of the Silver schema for a detail one. The
declared `type` selects which of those two key vocabularies the block is checked
against, rather than the keys themselves selecting the type. Every expression is
compiled once at construction, so a typo in a document fails loudly there rather
than the first time a posting reaches it.
"""

import html
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

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
_INDEX_JMESPATH_KEYS = frozenset({"postings", "posting_url"})

_TOP_LEVEL_KEYS = frozenset({"version", "type", "domains", "jmespath"})

_KIND_INDEX = "index"
_KIND_DETAIL = "detail"

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


def evaluate_expression(expression: str, document: dict | list) -> Any:
    """Evaluate *expression* against *document*, outside any mapping document.

    The engine's one door for an ad-hoc expression a document never declared, a
    spider's ``filter.`` key today. Compiling then searching with
    ``options=_OPTIONS`` explicitly, rather than the ``jmespath.search`` shortcut
    that defaults ``options`` to ``None``, keeps ``unescape``, ``markdown`` and the
    unknown-function walk below live for this caller too.
    """
    try:
        compiled = jmespath.compile(expression)
    except jmespath.exceptions.ParseError as exc:
        raise MappingError(
            f"invalid jmespath expression {expression!r}: {exc}"
        ) from exc
    except TypeError as exc:
        raise MappingError(f"jmespath expression must be a string: {exc}") from exc
    _validate_function_names(compiled.parsed)
    try:
        return compiled.search(document, options=_OPTIONS)
    except jmespath.exceptions.JMESPathError as exc:
        raise MappingError(f"evaluating {expression!r} failed: {exc}") from exc


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


def _validate_type(document: dict, expected: str) -> None:
    # Checked by the class itself, not only by load_mapping, so constructing
    # MappedIndex/MappedDetail directly cannot get round the declaration.
    kind = document.get("type")
    if kind != expected:
        raise MappingError(f"expected type {expected!r}, found {kind!r}")


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
        _validate_type(document, _KIND_INDEX)
        self.domains: list[str] = _validate_domains(document)
        self._compiled = _compile_jmespath_block(document, _INDEX_JMESPATH_KEYS)
        missing = _INDEX_JMESPATH_KEYS - self._compiled.keys()
        if missing:
            raise MappingError(f"index document missing key(s): {sorted(missing)}")

    def references(self, document: dict | list, start_url: str) -> list[PostingRef]:
        try:
            postings = self._compiled["postings"].search(document, options=_OPTIONS)
        except jmespath.exceptions.JMESPathError as exc:
            logger.error("postings expression raised for %s: %s", start_url, exc)
            return []
        if not isinstance(postings, list):
            logger.error(
                "postings expression for %s resolved to %s, not a list",
                start_url,
                type(postings).__name__,
            )
            return []
        posting_url_expr = self._compiled["posting_url"]
        refs = []
        for element in postings:
            # One posting's surprise (a raise, or a shape posting_url can't resolve
            # into an identity) is never evidence about the rest of the response.
            try:
                url = posting_url_expr.search(element, options=_OPTIONS)
            except jmespath.exceptions.JMESPathError as exc:
                logger.error(
                    "posting_url expression raised for a posting from %s: %s",
                    start_url,
                    exc,
                )
                continue
            if not isinstance(url, str) or not url:
                logger.error(
                    "posting_url expression resolved to %r, not a non-empty string,"
                    " for a posting from %s",
                    url,
                    start_url,
                )
                continue
            try:
                resolved_url = urljoin(start_url, url)
            except ValueError as exc:
                logger.error(
                    "posting_url %r for a posting from %s did not resolve to a URL: %s",
                    url,
                    start_url,
                    exc,
                )
                continue
            posting_document = element if isinstance(element, (dict, list)) else None
            refs.append(PostingRef(url=resolved_url, document=posting_document))
        return refs


class MappedDetail(DetailMapping):
    """A detail mapping interpreted from a document: reads a posting into Silver."""

    def __init__(self, document: dict) -> None:
        _validate_top_level(document)
        _validate_version(document)
        _validate_type(document, _KIND_DETAIL)
        self.domains: list[str] = _validate_domains(document)
        self._compiled = _compile_jmespath_block(document, _SILVER_SCHEMA_KEYS)

    def to_silver(self, document: dict | list) -> dict:
        return {
            key: expr.search(document, options=_OPTIONS)
            for key, expr in self._compiled.items()
        }


def load_mapping(document: dict) -> IndexMapping | DetailMapping:
    """Build the mapping *document* describes, dispatched on its own ``type``."""
    _validate_top_level(document)
    kind = document.get("type")
    if kind == _KIND_INDEX:
        return MappedIndex(document)
    if kind == _KIND_DETAIL:
        return MappedDetail(document)
    raise MappingError(f"unknown mapping type: {kind!r}")


def load_mapping_file(path: Path) -> IndexMapping | DetailMapping:
    """``json.load`` *path* and build the mapping it describes."""
    return load_mapping(json.loads(path.read_text()))
