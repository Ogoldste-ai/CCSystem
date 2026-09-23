from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import TeamsConfig
from ..models import Chat, Message, parse_timestamp, strip_html

# Power Automate's JSON shape depends on how the flow is authored, so accept the
# handful of spellings a reasonable flow produces rather than forcing one.
_ID_KEYS = ("id", "messageId", "message_id")
_CHAT_KEYS = ("chatId", "chat_id", "conversationId", "conversation_id")
_CHAT_NAME_KEYS = ("chatName", "chat_name", "topic", "conversationTopic")
_SENDER_KEYS = ("from", "sender", "fromName", "displayName")
_EMAIL_KEYS = ("fromEmail", "from_email", "senderEmail", "email", "userPrincipalName")
_BODY_KEYS = ("body", "content", "text", "messageBody")
_TIME_KEYS = ("createdAt", "created_at", "createdDateTime", "timestamp")
_URL_KEYS = ("webUrl", "web_url", "link", "linkToMessage")


def _first(payload: dict[str, Any], keys: tuple[str, ...], default: str = "") -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            for nested in ("displayName", "content", "name", "email"):
                inner = value.get(nested)
                if inner:
                    return str(inner).strip()
            continue
        if value not in (None, ""):
            return str(value).strip()
    return default


class FileDropBackend:
    """Reads messages dropped as JSON files by a Power Automate flow.

    This backend exists because Power Automate's Teams connector needs no Entra
    app registration or admin consent, while its HTTP trigger is premium-only.
    A synced folder is therefore the cheapest bridge between the cloud flow and
    this local process. Reading needs no credentials at all.
    """

    name = "filedrop"

    def __init__(self, config: TeamsConfig) -> None:
        self.config = config

    def _inbox(self) -> Path:
        self.config.require_ready()
        assert self.config.inbox_dir is not None
        return self.config.inbox_dir

    def health(self) -> dict[str, Any]:
        inbox = self.config.inbox_dir
        outbox = self.config.outbox_dir
        info: dict[str, Any] = {
            "backend": self.name,
            "inbox_dir": str(inbox) if inbox else None,
            "outbox_dir": str(outbox) if outbox else None,
        }
        if inbox and inbox.is_dir():
            info["messages_on_disk"] = sum(1 for _ in inbox.glob("*.json"))
        return info

    def _load_all(self) -> list[Message]:
        messages: list[Message] = []
        for path in self._inbox().glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # A file mid-sync is normal; skip it and pick it up next call
                # rather than failing the whole listing.
                continue
            if isinstance(payload, list):
                messages.extend(self._parse(item, path) for item in payload if isinstance(item, dict))
            elif isinstance(payload, dict):
                messages.append(self._parse(payload, path))
        messages.sort(key=lambda item: item.sort_key())
        return messages

    def _parse(self, payload: dict[str, Any], path: Path) -> Message:
        raw_body = _first(payload, _BODY_KEYS)
        return Message(
            id=_first(payload, _ID_KEYS) or path.stem,
            chat_id=_first(payload, _CHAT_KEYS),
            chat_name=_first(payload, _CHAT_NAME_KEYS),
            sender=_first(payload, _SENDER_KEYS),
            sender_email=_first(payload, _EMAIL_KEYS),
            created_at=_first(payload, _TIME_KEYS),
            body=strip_html(raw_body),
            web_url=_first(payload, _URL_KEYS),
        )

    def list_chats(self, limit: int = 20) -> list[Chat]:
        chats: dict[str, Chat] = {}
        for message in self._load_all():
            if not message.chat_id:
                continue
            chat = chats.get(message.chat_id)
            if chat is None:
                chat = Chat(id=message.chat_id, topic=message.chat_name)
                chats[message.chat_id] = chat
            if message.sender and message.sender not in chat.members:
                chat.members.append(message.sender)
            if message.created_at > chat.last_updated:
                chat.last_updated = message.created_at
        ordered = sorted(chats.values(), key=lambda item: item.last_updated, reverse=True)
        return ordered[:limit]

    def fetch_messages(self, chat_id: str, since: str = "", limit: int = 50) -> list[Message]:
        cutoff = parse_timestamp(since)
        selected = [
            message
            for message in self._load_all()
            if (not chat_id or message.chat_id == chat_id)
            and (cutoff is None or message.sort_key() > cutoff)
        ]
        return selected[-limit:] if limit > 0 else selected

    def fetch_recent(self, since: str = "", limit: int = 50) -> list[Message]:
        cutoff = parse_timestamp(since)
        selected = [
            message
            for message in self._load_all()
            if cutoff is None or message.sort_key() > cutoff
        ]
        selected.reverse()
        return selected[:limit] if limit > 0 else selected

    def send_reply(self, chat_id: str, body: str) -> dict[str, Any]:
        self.config.require_ready()
        outbox = self.config.outbox_dir
        if outbox is None:
            raise RuntimeError("TEAMS_OUTBOX_DIR is not set, so replies have nowhere to go.")
        outbox.mkdir(parents=True, exist_ok=True)
        created = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        reply_id = uuid.uuid4().hex[:12]
        target = outbox / f"reply-{created}-{reply_id}.json"
        payload = {
            "chatId": chat_id,
            "body": body,
            "queuedAt": datetime.now(timezone.utc).isoformat(),
            "replyId": reply_id,
        }
        handle, tmp_name = tempfile.mkstemp(dir=str(outbox), prefix=".reply-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as tmp:
                json.dump(payload, tmp, indent=2)
            # Rename into place so the sync agent and the flow never observe a
            # partially written file and post a truncated message.
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return {
            "queued": True,
            "backend": self.name,
            "chat_id": chat_id,
            "reply_id": reply_id,
            "path": str(target),
            "note": (
                "Queued for the Power Automate flow. Delivery is not immediate - the file "
                "must sync and the flow must poll before the message appears in Teams."
            ),
        }
