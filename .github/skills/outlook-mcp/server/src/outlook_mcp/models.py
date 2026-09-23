from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .formatting import (
    cap_recipients,
    clean_text,
    html_to_text,
    preview_of,
    shape_body,
)


@dataclass(slots=True)
class MailMessage:
    """One mail item, normalised away from COM's awkward surface."""

    entry_id: str = ""
    subject: str = ""
    sender_name: str = ""
    sender_email: str = ""
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    received: str = ""
    unread: bool = False
    has_attachments: bool = False
    attachments: list[str] = field(default_factory=list)
    folder: str = ""
    importance: str = "normal"
    conversation_id: str = ""
    preview: str = ""
    body: str = ""
    body_truncated: bool = False
    body_info: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(
        cls,
        raw: dict[str, Any],
        preview_chars: int = 400,
        include_body: bool = False,
        max_body_chars: int = 0,
        include_quoted: bool = False,
        body_offset: int = 0,
    ) -> "MailMessage":
        body_raw = str(raw.get("body") or "")
        is_html = bool(raw.get("is_html"))
        preview, truncated = preview_of(body_raw, is_html, preview_chars)
        full = ""
        info: dict[str, Any] = {}
        if include_body:
            flat = html_to_text(body_raw) if is_html else clean_text(body_raw)
            full, info = shape_body(
                flat,
                include_quoted=include_quoted,
                offset=body_offset,
                limit=max_body_chars,
            )
        return cls(
            entry_id=str(raw.get("entry_id") or ""),
            subject=str(raw.get("subject") or "(no subject)"),
            sender_name=str(raw.get("sender_name") or ""),
            sender_email=str(raw.get("sender_email") or ""),
            to=list(raw.get("to") or []),
            cc=list(raw.get("cc") or []),
            received=str(raw.get("received") or ""),
            unread=bool(raw.get("unread")),
            has_attachments=bool(raw.get("has_attachments")),
            attachments=list(raw.get("attachments") or []),
            folder=str(raw.get("folder") or ""),
            importance=str(raw.get("importance") or "normal"),
            conversation_id=str(raw.get("conversation_id") or ""),
            preview=preview,
            body=full,
            # When the body is included in full nothing was cut, so the flag
            # must describe the preview only when the preview is all there is.
            body_truncated=False if include_body else truncated,
            body_info=info,
        )

    def to_dict(self, max_recipients: int = 0) -> dict[str, Any]:
        data: dict[str, Any] = {
            "entry_id": self.entry_id,
            "subject": self.subject,
            "from": {"name": self.sender_name, "email": self.sender_email},
            "to": cap_recipients(self.to, max_recipients),
            "received": self.received,
            "unread": self.unread,
            "folder": self.folder,
            "preview": self.preview,
        }
        if self.cc:
            data["cc"] = cap_recipients(self.cc, max_recipients)
        if self.has_attachments:
            data["attachments"] = self.attachments
        if self.importance != "normal":
            data["importance"] = self.importance
        if self.conversation_id:
            data["conversation_id"] = self.conversation_id
        if self.body or self.body_info:
            data["body"] = self.body
            data.update(self.body_info)
            if self.body_info.get("body_truncated"):
                data["hint"] = (
                    "Body truncated. Call get_message(entry_id, "
                    f"body_offset={self.body_info.get('body_next_offset', 0)}) "
                    "for the next part."
                )
            elif self.body_info.get("quoted_history_chars_removed"):
                data["hint"] = (
                    "Quoted reply history was removed. Pass include_quoted=True "
                    "to get the whole thread."
                )
        if self.body_truncated:
            data["body_truncated"] = True
            data["hint"] = "Preview only. Call get_message(entry_id) for the full body."
        return data
