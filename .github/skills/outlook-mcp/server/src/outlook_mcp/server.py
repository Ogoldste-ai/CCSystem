from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import OutlookConfig
from .models import CalendarEvent, MailMessage
from .outlook import OutlookClient


def build_server(config: OutlookConfig | None = None, client: OutlookClient | None = None) -> FastMCP:
    config = config or OutlookConfig.from_env()
    client = client or OutlookClient(config)
    server = FastMCP("outlook")

    def _cap(limit: int) -> int:
        return max(1, min(int(limit or 1), config.max_results))

    def _shape(
        raw: dict[str, Any],
        include_body: bool = False,
        include_quoted: bool = False,
        body_offset: int = 0,
    ) -> dict[str, Any]:
        message = MailMessage.from_raw(
            raw,
            preview_chars=config.preview_chars,
            include_body=include_body,
            max_body_chars=config.max_body_chars,
            include_quoted=include_quoted,
            body_offset=body_offset,
        )
        # List results cap recipients; a single message shows everyone, since
        # knowing exactly who was on a mail matters when you reply to it.
        return message.to_dict(max_recipients=0 if include_body else config.list_recipients)

    def _annotate(
        shaped: list[dict[str, Any]], stats: dict[str, Any], requested: int = 0
    ) -> list[dict[str, Any]]:
        """Tell the caller when the answer is partial.

        The result is a plain array, so there is nowhere to hang metadata except
        on an entry. Marking the last one keeps the schema intact while making
        silent truncation visible - previously a full page of results was
        indistinguishable from "that is everything".
        """
        if not shaped or not stats.get("more_available"):
            return shaped
        if stats.get("hit_limit"):
            # Saying "raise limit" is useless advice when the server-side cap,
            # not the caller's argument, is what actually stopped the scan.
            if requested > config.max_results:
                reason = (
                    f"Capped at OUTLOOK_MAX_RESULTS={config.max_results} (you asked for "
                    f"{requested}). Raise that env var, or narrow with `days`/`folder`."
                )
            else:
                reason = (
                    "Result limit reached - raise `limit` (up to "
                    f"OUTLOOK_MAX_RESULTS={config.max_results}) or narrow with "
                    "`days`/`folder` for more."
                )
        else:
            reason = (
                f"Scan stopped after {stats.get('scanned', 0)} of "
                f"{stats.get('folder_items', 0)} items in this folder; older matches "
                "may exist. Narrow with `days` or `folder`."
            )
        shaped[-1]["more_available"] = True
        shaped[-1]["scan_hint"] = reason
        return shaped

    @server.tool()
    def health() -> dict[str, Any]:
        """Report Outlook connectivity, the mailbox in use, and whether writes are enabled."""
        info: dict[str, Any] = {
            "status": "ok",
            "write_enabled": config.allow_write,
            "send_enabled": config.allow_write and config.allow_send,
            "preview_chars": config.preview_chars,
            "max_results": config.max_results,
            "max_body_chars": config.max_body_chars,
            "list_recipients": config.list_recipients,
            "problems": config.problems(),
        }
        if info["problems"]:
            info["status"] = "misconfigured"
        try:
            info["outlook"] = client.health()
        except Exception as exc:  # health must never be the thing that breaks
            info["status"] = "error"
            info["outlook"] = {"error": str(exc)}
        return info

    @server.tool()
    def list_folders(max_depth: int = 3) -> list[dict[str, Any]]:
        """List mail folders with item and unread counts.

        Use the returned `path` with list_messages. Paths look like
        'Inbox', 'Inbox/Projects', or 'Archive/2025'.
        """
        return list(client.iter_folders(max_depth=max(1, min(max_depth, 8))))

    @server.tool()
    def list_messages(
        folder: str = "Inbox",
        limit: int = 25,
        unread_only: bool = False,
        days: int = 0,
        from_contains: str = "",
        subject_contains: str = "",
    ) -> list[dict[str, Any]]:
        """List messages in a folder, newest first.

        Returns headers plus a short preview, not full bodies - call
        get_message(entry_id) for the complete text of one message. `days`
        limits the search to recent mail and makes large folders much faster.
        """
        raws = client.list_raw(
            folder_path=folder,
            limit=_cap(limit),
            unread_only=unread_only,
            days=max(0, int(days or 0)),
            from_contains=from_contains,
            subject_contains=subject_contains,
            stats=(stats := {}),
        )
        return _annotate([_shape(raw) for raw in raws], stats, requested=int(limit or 0))

    @server.tool()
    def get_message(
        entry_id: str, include_quoted: bool = False, body_offset: int = 0
    ) -> dict[str, Any]:
        """Fetch one message in full, including the body.

        `entry_id` comes from list_messages or search_messages. The quoted
        reply chain is dropped by default - set `include_quoted=True` to keep
        it. Long bodies are cut at OUTLOOK_MAX_BODY_CHARS; when that happens
        the result carries `body_next_offset`, which you pass back as
        `body_offset` to read the next part.
        """
        if not entry_id.strip():
            raise ValueError("entry_id is required.")
        return _shape(
            client.get_raw(entry_id.strip()),
            include_body=True,
            include_quoted=include_quoted,
            body_offset=max(0, int(body_offset or 0)),
        )

    @server.tool()
    def search_messages(
        query: str, folder: str = "Inbox", limit: int = 25, days: int = 0
    ) -> list[dict[str, Any]]:
        """Find messages whose subject or sender matches `query`.

        This is a substring match over recent mail in one folder, not a full
        Outlook search. Narrow it with `folder` and `days` on a large mailbox.
        """
        if not query.strip():
            raise ValueError("query must not be empty.")
        capped = _cap(limit)
        days = max(0, int(days or 0))
        subject_stats: dict[str, Any] = {}
        by_subject = client.list_raw(
            folder_path=folder,
            limit=capped,
            days=days,
            subject_contains=query,
            stats=subject_stats,
        )
        sender_stats: dict[str, Any] = {}
        by_sender: list[dict[str, Any]] = []
        # Skip the second full scan when the subject pass already filled the
        # page; it could not contribute a visible result anyway.
        if len(by_subject) < capped:
            seen = {raw["entry_id"] for raw in by_subject}
            by_sender = [
                raw
                for raw in client.list_raw(
                    folder_path=folder,
                    limit=capped,
                    days=days,
                    from_contains=query,
                    stats=sender_stats,
                )
                if raw["entry_id"] not in seen
            ]
        merged = {
            "more_available": subject_stats.get("more_available")
            or sender_stats.get("more_available"),
            "hit_limit": subject_stats.get("hit_limit") or sender_stats.get("hit_limit"),
            "scanned": max(
                subject_stats.get("scanned", 0), sender_stats.get("scanned", 0)
            ),
            "folder_items": subject_stats.get("folder_items", 0),
        }
        return _annotate(
            [_shape(raw) for raw in (by_subject + by_sender)[:capped]],
            merged,
            requested=int(limit or 0),
        )

    @server.tool()
    def list_calendar_events(
        days_back: int = 7,
        days_forward: int = 0,
        limit: int = 50,
        include_all_day: bool = True,
        busy_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List calendar appointments around today, earliest first.

        Defaults to the last 7 days, which is what "what did I actually do
        this week" needs. Recurring meetings are expanded into their
        individual occurrences. Set `busy_only=True` to drop free blocks,
        which is what cancelled meetings report as; tentative meetings are
        kept, since an accepted meeting routinely stays tentative in Outlook.
        """
        raws = client.list_events(
            days_back=max(0, int(days_back or 0)),
            days_forward=max(0, int(days_forward or 0)),
            limit=_cap(limit),
            include_all_day=include_all_day,
            busy_only=busy_only,
        )
        return [
            CalendarEvent.from_raw(raw, preview_chars=config.preview_chars).to_dict(
                max_recipients=config.list_recipients
            )
            for raw in raws
        ]

    @server.tool()
    def mark_read(entry_id: str, read: bool = True) -> dict[str, Any]:
        """Mark a message read or unread. Requires OUTLOOK_ALLOW_WRITE=1."""
        config.require_write()
        if not entry_id.strip():
            raise ValueError("entry_id is required.")
        return client.mark_read(entry_id.strip(), read=read)

    @server.tool()
    def create_draft(
        to: str, subject: str, body: str, cc: str = "", bcc: str = ""
    ) -> dict[str, Any]:
        """Save a draft in Outlook without sending it.

        Deliberately ungated: a draft sits in the Drafts folder and goes nowhere
        until you click Send yourself, so it is always the safe way to prepare
        mail. Separate addresses with ';' or ','.
        """
        if not to.strip():
            raise ValueError("to is required.")
        if not body.strip():
            raise ValueError("body must not be empty.")
        return client.create_draft(to=to, subject=subject, body=body, cc=cc, bcc=bcc)

    @server.tool()
    def send_mail(
        to: str, subject: str, body: str, cc: str = "", bcc: str = ""
    ) -> dict[str, Any]:
        """Send mail immediately from your own Outlook account.

        Requires OUTLOOK_ALLOW_WRITE=1. The message goes out under your real
        address and is indistinguishable from mail you typed, so confirm the
        exact recipients and wording with the user before calling this. It
        cannot be unsent. Prefer create_draft when there is any doubt.
        """
        config.require_send()
        if not to.strip():
            raise ValueError("to is required.")
        if not body.strip():
            raise ValueError("body must not be empty.")
        return client.send_mail(to=to, subject=subject, body=body, cc=cc, bcc=bcc)

    @server.tool()
    def reply_to_message(
        entry_id: str,
        body: str,
        reply_all: bool = False,
        send: bool = False,
        subject: str = "",
    ) -> dict[str, Any]:
        """Reply to a message, saving a draft by default.

        With send=False (the default) the reply is left in Drafts for you to
        review. send=True dispatches it immediately and requires
        OUTLOOK_ALLOW_WRITE=1; confirm the wording first, as it cannot be unsent.

        `subject` overrides Outlook's automatic "RE: <original>". Leave it empty
        for a normal reply; set it for a rolling series whose subject changes
        each time, such as a weekly report with a week number in it.
        """
        if not entry_id.strip():
            raise ValueError("entry_id is required.")
        if not body.strip():
            raise ValueError("body must not be empty.")
        if send:
            config.require_send()
        return client.reply(
            entry_id=entry_id.strip(),
            body=body,
            reply_all=reply_all,
            send=send,
            subject=subject,
        )

    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Microsoft Outlook MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
        help="MCP transport mode",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP transports")
    parser.add_argument("--port", type=int, default=8769, help="Port for HTTP transports")
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
