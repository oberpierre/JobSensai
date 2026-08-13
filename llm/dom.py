"""DOM utilities for adapter learning.

A real listing page is mostly link-free bulk (descriptions, footers, boilerplate) that
drowns the job links an LLM needs to see. These helpers resolve links to absolute URLs
and prune the page down to just its link-bearing skeleton.
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag


def resolve_hrefs(html: str, url: str) -> str:
    """Rewrite every ``<a href>`` to an absolute URL, honoring a ``<base href>``.

    Run before cleaning strips ``<head>``: single-page apps place job links relative to
    a ``<base>``, and resolving against the page URL alone doubles path segments.
    """
    soup = BeautifulSoup(html, "html.parser")
    base = url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base = urljoin(url, base_tag["href"])
    for anchor in soup.find_all("a", href=True):
        anchor["href"] = urljoin(base, anchor["href"])
    return str(soup)


def prune_to_links(html: str) -> str:
    """Remove every element that neither is nor contains a link.

    Each anchor keeps its inner markup, and the ancestor chain up to the root is kept,
    so the result preserves the containers a CSS selector keys off while dropping the
    link-free bulk of the page — small enough for an LLM to reason over directly.
    """
    soup = BeautifulSoup(html, "html.parser")

    keep: set[int] = {id(soup)}
    for anchor in soup.find_all("a", href=True):
        keep.add(id(anchor))
        keep.update(id(d) for d in anchor.descendants if isinstance(d, Tag))
        keep.update(id(p) for p in anchor.parents if isinstance(p, Tag))

    # Remove each non-kept node sitting directly under a kept one, because that
    # takes its whole (also-unwanted) subtree with it, so deeper nodes need no
    # separate handling.
    to_remove = [
        tag
        for tag in soup.find_all(True)
        if id(tag) not in keep and (tag.parent is None or id(tag.parent) in keep)
    ]
    for tag in to_remove:
        tag.decompose()
    return str(soup)
