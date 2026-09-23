from __future__ import annotations

import html
import re
from typing import Any

_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_END = re.compile(r"</(p|div|tr|li|h[1-6]|table|blockquote)>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_BLANK_RUN = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")

# Outlook wraps quoted history in these; cutting at the first one keeps a long
# reply chain from swamping a preview with text the reader has already seen.
_QUOTE_MARKERS = (
    "\n-----Original Message-----",
    "\n________________________________",
    "\nFrom: ",
)

# The Gmail/Apple style attribution. A bare "\nOn " is far too eager: ordinary
# prose starting a line with "On " would silently amputate the body, so require
# the closing "wrote:" of the real attribution line.
_QUOTE_PATTERNS = (re.compile(r"\nOn\b[^\n]{0,300}?\bwrote:", re.IGNORECASE),)


def html_to_text(raw: str) -> str:
    """Flatten an HTML mail body to readable plain text.

    Deliberately not a full HTML parser: mail bodies are messy and this only
    needs to produce something a human and a model can read, not round-trip.
    """
    if not raw:
        return ""
    text = _SCRIPT_OR_STYLE.sub(" ", raw)
    text = _BREAK.sub("\n", text)
    # Block ends become a blank line so paragraphs stay visually separate;
    # a single newline would run them together and lose the structure.
    text = _BLOCK_END.sub("\n\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = _TRAILING_SPACE.sub("\n", text)
    return _BLANK_RUN.sub("\n\n", text).strip()


def clean_text(raw: str) -> str:
    """Normalise an already-plain body without destroying its structure."""
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = _TRAILING_SPACE.sub("\n", text)
    return _BLANK_RUN.sub("\n\n", text).strip()


def strip_quoted_history(text: str) -> str:
    """Drop the quoted reply chain, keeping only what this sender actually wrote."""
    if not text:
        return ""
    cut = len(text)
    for marker in _QUOTE_MARKERS:
        found = text.find(marker)
        # Ignore a marker at the very start: that means the whole body is quoted
        # history, and returning an empty string would be worse than keeping it.
        if 0 < found < cut:
            cut = found
    for pattern in _QUOTE_PATTERNS:
        match = pattern.search(text)
        if match and 0 < match.start() < cut:
            cut = match.start()
    return text[:cut].strip()


def truncate(text: str, limit: int) -> tuple[str, bool]:
    """Cut text to `limit` characters, preferring a word boundary.

    Returns the text and whether anything was removed, so callers can say so
    explicitly instead of silently handing back a partial body.
    """
    if limit <= 0 or len(text) <= limit:
        return text, False
    window = text[:limit]
    space = window.rfind(" ")
    if space > limit * 0.6:
        window = window[:space]
    return window.rstrip() + " ...", True


def preview_of(body: str, is_html: bool, limit: int) -> tuple[str, bool]:
    """Build the short preview shown in list results."""
    text = html_to_text(body) if is_html else clean_text(body)
    return truncate(strip_quoted_history(text), limit)


def cap_recipients(values: list[str], limit: int) -> list[str]:
    """Shorten a recipient list for list results, noting how many were dropped.

    A mail with 50 recipients is not more informative than one showing the
    first few; dumping every address made list output unreadably large.
    `limit <= 0` means no cap, which is what a single-message view wants.
    """
    if limit <= 0 or len(values) <= limit:
        return list(values)
    remaining = len(values) - limit
    return [*values[:limit], f"+{remaining} more"]


def shape_body(
    text: str,
    include_quoted: bool = False,
    offset: int = 0,
    limit: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Cut a full body down to something readable, and say exactly what was cut.

    Two different things bloat a body: the quoted reply chain, and sheer
    length. Both are handled here so a caller always learns the original size
    and how to page through the rest, rather than silently getting a fragment.
    """
    info: dict[str, Any] = {}
    quoted_removed = 0
    if not include_quoted:
        kept = strip_quoted_history(text)
        if kept and len(kept) < len(text):
            quoted_removed = len(text) - len(kept)
            text = kept

    total = len(text)
    offset = max(0, min(int(offset or 0), total))
    window = text[offset:]
    truncated = False
    if limit > 0 and len(window) > limit:
        window = window[:limit]
        truncated = True

    info["body_chars"] = len(window)
    info["body_total_chars"] = total
    if offset:
        info["body_offset"] = offset
    if truncated:
        info["body_truncated"] = True
        info["body_next_offset"] = offset + len(window)
    if quoted_removed:
        info["quoted_history_chars_removed"] = quoted_removed
    return window, info


def split_addresses(raw: str) -> list[str]:
    """Split a user-supplied recipient string on the usual separators."""
    if not raw:
        return []
    parts = re.split(r"[;,]", raw)
    return [part.strip() for part in parts if part.strip()]
