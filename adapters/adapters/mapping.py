"""The mapping engine: interprets a parsing rule expressed as a JMESPath document.

One JMESPath expression per declared key, compiled once at construction so a typo in a
document fails loudly there rather than the first time a posting reaches it. See
``README.md``'s Shared contracts for the document shape.
"""

import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import jmespath
from jmespath import functions

from adapters.adapters._markdown import html_to_markdown
from adapters.adapters.base import DetailMapping, IndexMapping, PostingRef

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


def _compile_jmespath_block(document: dict, allowed_keys: frozenset) -> dict:
    block = document.get("jmespath")
    if not isinstance(block, dict):
        raise MappingError("'jmespath' must be an object")
    compiled = {}
    for key, expression in block.items():
        if key not in allowed_keys:
            raise MappingError(f"unknown jmespath key: {key!r}")
        parsed = jmespath.compile(expression)
        _validate_function_names(parsed.parsed)
        compiled[key] = parsed
    return compiled


class MappedIndex(IndexMapping):
    """An index mapping interpreted from a document: finds postings and their URLs."""

    def __init__(self, document: dict) -> None:
        _validate_top_level(document)
        self.domains: list[str] = list(document.get("domains", []))
        self._compiled = _compile_jmespath_block(document, _INDEX_JMESPATH_KEYS)

    def fetch_url(self, start_url: str) -> str:
        parts = urlsplit(start_url)
        kept = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.startswith("filter.")
        ]
        return urlunsplit(parts._replace(query=urlencode(kept)))

    def references(self, document: dict, start_url: str) -> list[PostingRef]:
        postings_expr = self._compiled.get("postings")
        job_url_expr = self._compiled.get("job_url")
        postings = (
            postings_expr.search(document, options=_OPTIONS) if postings_expr else None
        )
        refs = []
        for element in postings or []:
            url = (
                job_url_expr.search(element, options=_OPTIONS) if job_url_expr else None
            )
            refs.append(PostingRef(url=url, document=element))
        return refs


class MappedDetail(DetailMapping):
    """A detail mapping interpreted from a document: reads a posting into Silver."""

    def __init__(self, document: dict) -> None:
        _validate_top_level(document)
        self.domains: list[str] = list(document.get("domains", []))
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
    if keys and keys <= _INDEX_JMESPATH_KEYS:
        return MappedIndex(document)
    if keys <= _SILVER_SCHEMA_KEYS:
        return MappedDetail(document)
    unknown = sorted(keys - _SILVER_SCHEMA_KEYS - _INDEX_JMESPATH_KEYS)
    raise MappingError(f"unknown jmespath key(s): {unknown}")


def load_mapping_file(path: Path) -> IndexMapping | DetailMapping:
    """``json.load`` *path* and build the mapping it describes."""
    return load_mapping(json.loads(path.read_text()))
