from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser

_BLOCK_END = re.compile(r"(?i)<(?:br\s*/?|/p|/li|/div|/h[1-6]|/tr|/ul|/ol)>")


def html_to_text(markup: str | None) -> str:
    """Convert HTML to plain text: inline tags joined, block ends become newlines."""
    if not markup:
        return ""
    root = LexborHTMLParser(_BLOCK_END.sub("\n", markup)).root
    if root is None:
        return ""
    text = root.text(separator="")
    text = re.sub(r"[ \t\r\f\v\xa0]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()
