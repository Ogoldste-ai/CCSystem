from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

from .backends.base import MessageSource
from .config import GRAPH, TeamsConfig
from .models import Message
from .sender import WebhookSender
from .store import SeenStore


def build_backend(config: TeamsConfig) -> MessageSource:
    if config.backend == GRAPH:
        from .backends.graph import GraphBackend

        return GraphBackend(config)
    from .backends.filedrop import FileDropBackend

    return FileDropBackend(config)


def _as_dicts(messages: list[Message]) -> list[dict[str, Any]]:
    return [message.to_dict() for message in messages]


def build_server(config: TeamsConfig | None = None) -> FastMCP:
    config = config or TeamsConfig.from_env()
    backend = build_backend(config)
    webhook = WebhookSender(config)
    store = SeenStore(config.state_file)
    server = FastMCP("teams")

    @server.tool()
    def health() -> dict[str, Any]:
        """Report backend status, configuration problems, and whether replies are enabled."""
        info: dict[str, Any] = {
            "status": "ok",
            "backend": config.backend,
            "write_enabled": config.allow_write,
            "problems": config.problems(),
        }
        if info["problems"]:
            info["status"] = "misconfigured"
        try:
            info["details"] = backend.health()
        except Exception as exc:  # health must never be the thing that breaks
            info["status"] = "error"
            info["details"] = {"error": str(exc)}
        info["webhook"] = webhook.describe()
        info["seen_state"] = store.stats()
        return info

    @server.tool()
    def list_chats(limit: int = 20) -> list[dict[str, Any]]:
        """List your Teams chats, most recently active first.

        Use this to find the chat_id needed by read_messages and reply_to_chat.
        """
        return [chat.to_dict() for chat in backend.list_chats(limit=limit)]

    @server.tool()
    def read_messages(chat_id: str = "", since: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """Read messages from one chat, oldest first.

        `since` is an ISO-8601 timestamp; only later messages are returned. The
        graph backend requires a chat_id, the filedrop backend treats an empty
        chat_id as "every chat".
        """
        return _as_dicts(backend.fetch_messages(chat_id=chat_id, since=since, limit=limit))

    @server.tool()
    def get_message(message_id: str, chat_id: str = "") -> dict[str, Any]:
        """Fetch a single message by id."""
        for message in backend.fetch_messages(chat_id=chat_id, limit=200):
            if message.id == message_id:
                return message.to_dict()
        return {"found": False, "message_id": message_id}

    @server.tool()
    def check_new_messages(limit: int = 25, mark_seen: bool = True) -> dict[str, Any]:
        """Messages that have arrived since the last time this tool was called.

        This is the "did anyone message me?" alert. Already-reported messages are
        suppressed, so it is safe to call repeatedly. Pass mark_seen=false to peek
        without consuming them.
        """
        recent = backend.fetch_recent(limit=max(limit * 2, limit))
        fresh = [
            message
            for message in recent
            if message.id and not store.has_seen(message.id) and not message.is_from_me
        ]
        fresh = fresh[:limit]
        if mark_seen and fresh:
            store.mark_seen(message.id for message in fresh)
            store.save()
        return {
            "new_count": len(fresh),
            "marked_seen": bool(mark_seen and fresh),
            "messages": _as_dicts(fresh),
        }

    @server.tool()
    def reply_to_chat(chat_id: str, body: str) -> dict[str, Any]:
        """Post a reply into a specific chat. Requires TEAMS_ALLOW_WRITE=1.

        Needs a chat_id from list_chats, so it only works once a read backend is
        supplying chats. To send to a fixed destination without any read backend,
        use send_message instead.

        On the graph backend the message is posted under your own Teams identity -
        recipients cannot tell it was drafted. Confirm the exact wording with the
        user before calling this.
        """
        config.require_write()
        if not chat_id:
            raise ValueError("chat_id is required.")
        if not body.strip():
            raise ValueError("body must not be empty.")
        return backend.send_reply(chat_id=chat_id, body=body)

    @server.tool()
    def send_message(body: str, title: str = "") -> dict[str, Any]:
        """Send a message through the configured Teams Workflows webhook.

        Requires TEAMS_ALLOW_WRITE=1 and TEAMS_WEBHOOK_URL. Delivery is immediate
        and needs no admin consent, but the destination is fixed by the webhook
        URL - it always goes to the one chat or channel the webhook was created
        for, and it arrives as the Workflows bot rather than as you.

        Confirm the exact wording with the user before calling this; a Teams
        message notifies people and cannot be unsent.
        """
        config.require_write()
        if not body.strip():
            raise ValueError("body must not be empty.")
        return webhook.send(body=body, title=title)

    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Microsoft Teams MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
        help="MCP transport mode",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP transports")
    parser.add_argument("--port", type=int, default=8768, help="Port for HTTP transports")
    parser.add_argument("--path", default="/mcp", help="Path for streamable HTTP transport")
    parser.add_argument("--sse-path", default="/sse", help="Path for SSE transport")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = build_server()

    if args.transport == "stdio":
        server.run()
        return

    server.settings.host = args.host
    server.settings.port = args.port
    server.settings.streamable_http_path = args.path
    server.settings.sse_path = args.sse_path
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
