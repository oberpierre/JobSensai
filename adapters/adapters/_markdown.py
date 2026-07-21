"""Deterministic HTML -> Markdown for job descriptions.

Every extraction adapter renders its description through this one converter instead of
each generated adapter inventing its own, so the stored markdown is consistent and a
markdownify upgrade is caught by the adapters' snapshots rather than silently drifting.
Wrapped behind ``html_to_markdown`` so the escaping / heading policy lives in one
swappable place.
"""

import re

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

_HEADING_RE = re.compile(r"^h[1-6]$")


class _JobDescriptionConverter(MarkdownConverter):
    """markdownify tuned for job-posting bodies.

    The extension point for per-need description tweaks; options (ATX headings, ``-``
    bullets, images stripped) are applied in ``html_to_markdown``.
    """


def _relevel_headings(soup: BeautifulSoup) -> None:
    """Shift headings so the shallowest present becomes ``#``, keeping source gaps.

    Boards differ on where their headings start (one uses ``h2``, another ``h3``), so
    the description is normalised to begin at level 1 and the frontend re-levels from
    there. Relative depth is preserved (``h3``/``h5`` -> ``#``/``###``), not compressed,
    to stay faithful to the board's own structure.
    """
    headings = soup.find_all(_HEADING_RE)
    levels = [int(tag.name[1]) for tag in headings]
    offset = min(levels) - 1 if levels else 0
    if offset <= 0:
        return
    for tag in headings:
        tag.name = f"h{max(1, int(tag.name[1]) - offset)}"


def html_to_markdown(node) -> str:
    """Convert an HTML fragment (a bs4 node or an HTML string) to markdown.

    Re-parses the input so the caller's tree is never mutated by re-levelling.
    """
    soup = BeautifulSoup(str(node), "html.parser")
    _relevel_headings(soup)
    converter = _JobDescriptionConverter(
        heading_style="ATX", bullets="-", strip=["img"]
    )
    return converter.convert_soup(soup).strip()
