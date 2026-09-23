from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_HTML_BREAKS = ("<br>", "<br/>", "<br />", "</p>", "</div>")


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating the trailing ``Z`` Graph emits."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def strip_html(value: str) -> str:
    """Flatten Teams' HTML message bodies to readable plain text.

    Teams returns ``contentType: html`` for most messages. Keeping the raw
    markup would waste context and make the text hard to read, so block-level
    tags become newlines and everything else is dropped.
    """
    if not value:
        return ""
    text = value
    for token in _HTML_BREAKS:
        text = text.replace(token, "\n")
    out: list[str] = []
    depth = 0
    for char in text:
        if char == "<":
            depth += 1
        elif char == ">":
            if depth:
                depth -= 1
        elif depth == 0:
            out.append(char)
    flattened = (
        "".join(out)
        .replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    lines = [line.strip() for line in flattened.splitlines()]
    return "\n".join(line for line in lines if line).strip()


@dataclass(slots=True)
class Chat:
    id: str
    topic: str = ""
    kind: str = ""
    members: list[str] = field(default_factory=list)
    last_updated: str = ""
    web_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic or self.display_name(),
            "kind": self.kind,
            "members": self.members,
            "last_updated": self.last_updated,
            "web_url": self.web_url,
        }

    def display_name(self) -> str:
        if self.topic:
            return self.topic
        if self.members:
            return ", ".join(self.members[:3]) + (" +more" if len(self.members) > 3 else "")
        return self.id


@dataclass(slots=True)
class Message:
    id: str
    chat_id: str
    body: str
    sender: str = ""
    sender_email: str = ""
    created_at: str = ""
    chat_name: str = ""
    is_from_me: bool = False
    web_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "chat_name": self.chat_name,
            "sender": self.sender,
            "sender_email": self.sender_email,
            "created_at": self.created_at,
            "is_from_me": self.is_from_me,
            "body": self.body,
            "web_url": self.web_url,
        }

    def sort_key(self) -> datetime:
        return parse_timestamp(self.created_at) or datetime.min.replace(tzinfo=timezone.utc)
