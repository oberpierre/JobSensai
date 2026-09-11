"""The ``filter.`` query-parameter convention: the prefix and both operations over it.

Stripping the parameters out of a URL and reading them back off one are inverse, so
both decide by the percent-decoded key and neither spells the prefix itself. Imports
nothing from ``adapters``, which is what lets ``base.py`` import this module without a
cycle.
"""

from urllib.parse import parse_qsl, unquote_plus, urlsplit, urlunsplit

FILTER_PREFIX = "filter."


def strip_filter_params(url: str) -> str:
    """Remove every ``filter.``-prefixed query parameter from *url*, textually.

    Every other character is left exactly as it was: the operator's URL is the one
    thing only a human can supply, so a round trip through ``parse_qsl``/``urlencode``
    that re-encodes what it keeps is not an option.
    """
    parts = urlsplit(url)
    kept = [
        pair
        for pair in parts.query.split("&")
        if pair and not unquote_plus(pair.split("=", 1)[0]).startswith(FILTER_PREFIX)
    ]
    return urlunsplit(parts._replace(query="&".join(kept)))


def parse_filter_params(url: str) -> dict[str, list[str]]:
    """Return every ``filter.``-prefixed query parameter, keyed by its path."""
    filters: dict[str, list[str]] = {}
    for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True):
        if key.startswith(FILTER_PREFIX):
            filters.setdefault(key[len(FILTER_PREFIX) :], []).append(value)
    return filters
