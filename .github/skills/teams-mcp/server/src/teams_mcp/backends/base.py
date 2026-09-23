from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import Chat, Message


@runtime_checkable
class MessageSource(Protocol):
    """Where messages come from.

    The two implementations - Microsoft Graph and a synced file drop - differ
    only in transport. Every tool in ``server.py`` is written against this
    protocol, so the backend can be swapped with one environment variable and
    neither implementation can drift away from the other's shape.
    """

    name: str

    def health(self) -> dict:
        """Backend-specific status. Must never raise."""

    def list_chats(self, limit: int = 20) -> list[Chat]:
        """Most recently active chats first."""

    def fetch_messages(self, chat_id: str, since: str = "", limit: int = 50) -> list[Message]:
        """Messages in one chat, oldest first."""

    def fetch_recent(self, since: str = "", limit: int = 50) -> list[Message]:
        """Recent messages across all chats, newest first."""

    def send_reply(self, chat_id: str, body: str) -> dict:
        """Post a reply. Callers must check the write guard first."""
