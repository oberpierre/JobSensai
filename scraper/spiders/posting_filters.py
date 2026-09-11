"""The ``filter.`` query-parameter convention, applied to an API board's postings.

The convention spans two packages. Its other half is ``strip_filter_params`` in
``adapters/adapters/base.py``, which removes those parameters from the URL actually
requested, because ``IndexMapping.fetch_url`` delegates to it.
"""

import json
import logging
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from adapters.adapters.base import PostingRef
from adapters.adapters.mapping import MappingError, evaluate_expression

logger = logging.getLogger(__name__)


def apply_filters(
    refs: list[PostingRef], stored_url: str, hostname: str | None
) -> set[int] | None:
    """Return the ids of the references surviving every ``filter.`` key.

    None means the response is refused outright: an operator error in a
    filter key was found, either before or during the posting loop.
    """
    filters = _parse_filter_params(stored_url)
    doc_refs = [ref for ref in refs if ref.document is not None]

    for key in filters:
        try:
            evaluate_expression(key, {})
        except MappingError as exc:
            logger.error("filter.%s is invalid on %s: %s", key, hostname, exc)
            return None

    resolved = dict.fromkeys(filters, False)
    kept_ids: set[int] = set()
    for ref in doc_refs:
        raised = False
        matches = True
        for key, allowed in filters.items():
            try:
                result = evaluate_expression(key, ref.document)
            except MappingError as exc:
                # Data, not configuration: this one posting's value is odd,
                # so it alone is dropped rather than costing the whole board.
                logger.error(
                    "filter.%s raised for the posting at %s: %s",
                    key,
                    ref.url,
                    exc,
                )
                raised = True
                continue
            if result is not None:
                resolved[key] = True
            if not _filter_matches(result, allowed):
                matches = False
        if not raised and matches:
            kept_ids.add(id(ref))

    if doc_refs:
        unresolved = [key for key, hit in resolved.items() if not hit]
        for key in unresolved:
            logger.error(
                "filter.%s did not resolve on any posting on %s", key, hostname
            )
        if unresolved:
            return None
    return kept_ids


def _parse_filter_params(stored_url: str) -> dict[str, list[str]]:
    """Return every ``filter.``-prefixed query parameter, keyed by its path."""
    filters: dict[str, list[str]] = {}
    for key, value in parse_qsl(urlsplit(stored_url).query, keep_blank_values=True):
        if key.startswith("filter."):
            filters.setdefault(key[len("filter.") :], []).append(value)
    return filters


def _filter_matches(result: Any, allowed: list[str]) -> bool:
    """A path resolving to a list matches when any element does."""
    values = result if isinstance(result, list) else [result]
    return any(_canonical_filter_text(value) in allowed for value in values)


def _canonical_filter_text(value: Any) -> str | None:
    """Put an evaluated JSON value in the same terms as a query parameter's text.

    A JSON boolean compares as `true`/`false`, a number as its JSON text form,
    a string as itself, and `null` as not matching rather than the text "None".
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return value
    return None
