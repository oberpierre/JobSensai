"""Deterministic, selector-agnostic HTML cleaning for adapter learning.

Strips scripting/styling/head noise and inlined blobs so the HTML handed to the LLM
agents — and stored as a fixture — is small and structural, without needing to know
any selectors.
"""

from bs4 import BeautifulSoup, Comment

# Tags removed wholesale: they carry no structure a parser needs and are the bulk of
# page weight.
_STRIP_TAGS = ("script", "style", "svg", "noscript", "link", "meta", "head")

# Attributes that commonly hold large inlined blobs (data: URIs, inline CSS).
_URI_ATTRS = ("href", "src", "srcset")


def clean_html(html: str) -> str:
    """Return a structurally-equivalent but de-noised copy of *html*."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(list(_STRIP_TAGS)):
        tag.decompose()

    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()

    for element in soup.find_all(True):
        # Drop inlined data: URIs so base64 blobs don't dominate the output.
        for attr in _URI_ATTRS:
            value = element.get(attr)
            if isinstance(value, str) and value.strip().lower().startswith("data:"):
                del element[attr]
        # Inline styles are page weight with no structural value.
        if element.has_attr("style"):
            del element["style"]

    return str(soup)
