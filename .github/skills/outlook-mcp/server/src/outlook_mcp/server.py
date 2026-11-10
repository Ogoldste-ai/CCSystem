from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import OutlookConfig
from .models import CalendarEvent, Contact, MailMessage
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
        body_limit: int | None = None,
        bounded: bool = False,
    ) -> dict[str, Any]:
        message = MailMessage.from_raw(
            raw,
            preview_chars=min(config.preview_chars or 156, 156) if bounded else config.preview_chars,
            include_body=include_body,
            max_body_chars=config.max_body_chars if body_limit is None else body_limit,
            include_quoted=include_quoted,
            body_offset=body_offset,
        )
        # List results cap recipients; a single message shows everyone, since
        # knowing exactly who was on a mail matters when you reply to it.
        recipients = max(1, min(config.list_recipients or 3, 10)) if bounded else (
            0 if include_body else config.list_recipients
        )
        return message.to_dict(max_recipients=recipients)

    def _batch_ids(entry_ids: list[str]) -> list[str]:
        if not entry_ids or len(entry_ids) > config.max_results:
            raise ValueError(
                f"Supply 1 to OUTLOOK_MAX_RESULTS={config.max_results} entry IDs; "
                "split larger batches explicitly."
            )
        if any(not isinstance(entry_id, str) or not entry_id.strip() for entry_id in entry_ids):
            raise ValueError("Every entry_id must be a nonempty string.")
        return list(dict.fromkeys(entry_id.strip() for entry_id in entry_ids))

    def _batch_result(results: list[dict[str, Any]]) -> dict[str, Any]:
        failed = sum("error" in result for result in results)
        return {"results": results, "succeeded": len(results) - failed, "failed": failed}

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
            "attachment_dir": config.resolve_attachment_dir(),
            "max_attachment_mb": config.max_attachment_mb,
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
        received_after: str = "",
        received_before: str = "",
    ) -> list[dict[str, Any]]:
        """List messages in a folder, newest first.

        Returns headers plus a short preview, not full bodies - call
        get_message(entry_id) for the complete text of one message. `days`
        limits the search to recent mail and makes large folders much faster.
        received_after (inclusive) and received_before (exclusive) accept ISO
        dates/date-times; no offset means server-local time. Use
        list_messages_page to continue beyond the result or scan limit.
        """
        raws = client.list_raw(
            folder_path=folder,
            limit=_cap(limit),
            unread_only=unread_only,
            days=max(0, int(days or 0)),
            from_contains=from_contains,
            subject_contains=subject_contains,
            stats=(stats := {}),
            received_after=received_after,
            received_before=received_before,
        )
        return _annotate([_shape(raw) for raw in raws], stats, requested=int(limit or 0))

    @server.tool()
    def list_messages_page(
        folder: str = "Inbox",
        limit: int = 25,
        unread_only: bool = False,
        days: int = 0,
        from_contains: str = "",
        subject_contains: str = "",
        offset: int = 0,
        received_after: str = "",
        received_before: str = "",
        compact: bool = True,
    ) -> dict[str, Any]:
        """List a bounded page with next_offset, including across empty scan pages.

        Start at offset=0; keep identical filters and pass next_offset until
        more_available is false. OUTLOOK_MAX_RESULTS caps each page, not the
        total. ISO received_after is inclusive, received_before exclusive;
        offset-free dates use server-local midnight, ISO offsets are converted.
        compact returns key headers and a short preview.

        Offsets index a live sorted collection, not a snapshot. Gather pages
        before marking read; restart/deduplicate if mail arrives, moves or is
        deleted. Prefer fixed received bounds over rolling days when paging.
        """
        stats: dict[str, Any] = {}
        raws = client.list_raw(
            folder_path=folder,
            limit=_cap(limit),
            unread_only=unread_only,
            days=max(0, int(days or 0)),
            from_contains=from_contains,
            subject_contains=subject_contains,
            stats=stats,
            offset=offset,
            received_after=received_after,
            received_before=received_before,
        )
        messages = [_shape(raw, bounded=compact) for raw in raws]
        if compact:
            fields = {"entry_id", "subject", "from", "received", "unread", "attachments"}
            messages = [
                {
                    **{key: value for key, value in message.items() if key in fields},
                    "preview": message.get("preview", "")[:160],
                    "preview_truncated": len(message.get("preview", "")) > 160
                    or bool(message.get("body_truncated")),
                }
                for message in messages
            ]
        return {
            "messages": messages,
            "next_offset": stats.get("next_offset"),
            "more_available": stats.get("next_offset") is not None,
            "scanned": max(0, stats.get("scanned", offset) - offset),
        }

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
    def get_messages(
        entry_ids: list[str],
        include_quoted: bool = False,
        body_offset: int = 0,
        body_chars: int = 2000,
    ) -> dict[str, Any]:
        """Read an explicit batch of messages, with bounded bodies and per-ID errors.

        Supply at most OUTLOOK_MAX_RESULTS IDs. Duplicates are read once.
        body_chars is 1-10000 per message; the configured body cap and a
        100000-character batch body budget also apply. Truncated bodies carry
        body_next_offset for continuation via get_message. Never marks mail read.
        """
        ids = _batch_ids(entry_ids)
        if not 1 <= body_chars <= 10000 or body_offset < 0:
            raise ValueError("body_chars must be 1-10000 and body_offset must be nonnegative.")
        body_limit = min(body_chars, 100000 // len(ids))
        if config.max_body_chars > 0:
            body_limit = min(body_limit, config.max_body_chars)
        results: list[dict[str, Any]] = []
        for entry_id in ids:
            try:
                results.append(_shape(
                    client.get_raw(entry_id),
                    include_body=True,
                    include_quoted=include_quoted,
                    body_offset=body_offset,
                    body_limit=body_limit,
                    bounded=True,
                ))
            except Exception as exc:
                results.append({"entry_id": entry_id, "error": str(exc)})
        return _batch_result(results)

    @server.tool()
    def mark_messages_read(entry_ids: list[str], read: bool = True) -> dict[str, Any]:
        """Set read state on explicit reviewed IDs only. Requires OUTLOOK_ALLOW_WRITE.

        Validates the entire batch before writes; at most OUTLOOK_MAX_RESULTS
        IDs, duplicates handled once. Reports each saved state or failure and
        continues after an individual failure. This is not an atomic transaction.
        Collect all list pages before changing read state; never supplies a
        mailbox-wide mark-all operation.
        """
        config.require_write()
        ids = _batch_ids(entry_ids)
        results: list[dict[str, Any]] = []
        for entry_id in ids:
            try:
                results.append(client.mark_read(entry_id, read=read))
            except Exception as exc:
                results.append({"entry_id": entry_id, "error": str(exc)})
        return _batch_result(results)

    @server.tool()
    def list_attachments(entry_id: str) -> list[dict[str, Any]]:
        """List a message's attachments without extracting them.

        Reports each attachment's name, size in bytes, kind, and whether it is
        `inline` - a signature logo or other image embedded in the body rather
        than a document the sender meant to send. Use it to decide what is
        worth saving before calling save_attachments.
        """
        if not entry_id.strip():
            raise ValueError("entry_id is required.")
        return client.list_attachments(entry_id.strip())

    @server.tool()
    def save_attachments(
        entry_id: str,
        dest_dir: str = "",
        names: list[str] | None = None,
        include_inline: bool = False,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Save a message's attachments to a directory on this machine.

        This is how you get a mailed file into your own working area: pass the
        folder you want it in as `dest_dir` - an agent session folder, a scratch
        directory - and the files are written there. With `dest_dir` empty the
        server falls back to OUTLOOK_ATTACHMENT_DIR, and then to
        %LOCALAPPDATA%\\outlook-mcp\\attachments.

        By default every attachment is saved except inline images, nothing is
        overwritten (a colliding name gains a " (2)" suffix), and anything
        larger than OUTLOOK_MAX_ATTACHMENT_MB is skipped. Pass `names` to pick
        specific attachments by filename or 1-based index.

        Returns the absolute path and size of everything written, plus a
        `skipped` list explaining anything that was not, so a missing file is
        never silent. Attachment names are treated as untrusted: only the
        basename is used, so a file can never land outside `dest_dir`.
        """
        if not entry_id.strip():
            raise ValueError("entry_id is required.")
        config.require_attachment_write()
        return client.save_attachments(
            entry_id.strip(),
            dest_dir=config.resolve_attachment_dir(dest_dir),
            names=names or [],
            include_inline=include_inline,
            overwrite=overwrite,
            max_bytes=config.max_attachment_bytes,
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
    def search_contacts(
        query: str, limit: int = 10, include_gal: bool = True
    ) -> list[dict[str, Any]]:
        """Find a person's email address by name, alias or partial address.

        Searches your Contacts folder first, then the organisation's address
        book (GAL). Use this before mailing someone you have not corresponded
        with - searching mail folders for them will find nothing, because
        there is nothing there yet.

        The GAL matches on display name rather than alias, so "eran.raz" is
        tried as "Eran Raz" too; `matched` reports which spelling actually hit.
        Set `include_gal=False` to stay inside your own saved contacts.
        """
        if not query.strip():
            raise ValueError("query is required.")
        raws = client.search_contacts(
            query=query.strip(), limit=_cap(limit), include_gal=include_gal
        )
        return [Contact.from_raw(raw).to_dict() for raw in raws]

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
    def find_free_slots(
        attendees: str,
        start: str,
        end: str,
        duration_minutes: int = 30,
        work_start: str = "09:00",
        work_end: str = "18:00",
        workdays: str = "sun,mon,tue,wed,thu",
        limit: int = 10,
        allow_tentative: bool = False,
        include_me: bool = True,
    ) -> dict[str, Any]:
        """Find times when everyone is free (Scheduling Assistant equivalent).

        Read-only. Uses Exchange free/busy for you and the attendees (names or
        addresses, separated by ';' or ','). `start`/`end` bound the search as
        'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'. Only slots inside work_start..work_end
        on `workdays` are offered, earliest first. Tentative counts as busy
        unless allow_tentative. `no_data` lists people whose calendar could not be
        read (they are NOT checked); `unresolved` lists names that did not
        resolve. Tell the user about both.
        """
        return client.find_free_slots(
            attendees=attendees,
            start=start,
            end=end,
            duration_minutes=duration_minutes,
            work_start=work_start,
            work_end=work_end,
            workdays=workdays,
            limit=min(max(1, limit), config.max_results),
            allow_tentative=allow_tentative,
            include_me=include_me,
        )

    @server.tool()
    def create_meeting(
        attendees: str,
        subject: str,
        start: str,
        duration_minutes: int = 30,
        body: str = "",
        optional_attendees: str = "",
        location: str = "",
        teams: bool = True,
        send: bool = False,
    ) -> dict[str, Any]:
        """Create a meeting with attendees, optionally with a Teams link.

        By default (send=False) the invite is saved UNSENT in your Outlook
        Calendar and nobody is notified until you click Send there; this is
        ungated like create_draft. send=True mails the invitations immediately,
        requires OUTLOOK_ALLOW_WRITE=1, and cannot be undone - confirm the exact
        attendees, time and subject with the user first. `start` is
        'YYYY-MM-DD HH:MM' local time. teams=True briefly opens the invite window
        and clicks the Teams Meeting button (needs the Teams add-in and an English
        Outlook UI), so do not touch Outlook while it runs.
        """
        if send:
            config.require_send()
        if not subject.strip():
            raise ValueError("subject is required.")
        return client.create_meeting(
            attendees=attendees,
            subject=subject,
            start=start,
            duration_minutes=duration_minutes,
            body=body,
            optional_attendees=optional_attendees,
            location=location,
            teams=teams,
            send=send,
        )

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
        html_body: str = "",
    ) -> dict[str, Any]:
        """Reply to a message, saving a draft by default.

        With send=False (the default) the reply is left in Drafts for you to
        review. send=True dispatches it immediately and requires
        OUTLOOK_ALLOW_WRITE=1; confirm the wording first, as it cannot be unsent.

        `subject` overrides Outlook's automatic "RE: <original>". Leave it empty
        for a normal reply; set it for a rolling series whose subject changes
        each time, such as a weekly report with a week number in it.

        `html_body` is an optional HTML fragment for the new reply content.
        When supplied it replaces the plain-text `body` in the saved reply;
        Outlook's quoted original is HTML-escaped and retained underneath.
        Encode all mail-derived text before adding markup. No separate shell
        or COM formatting step is needed. Sending permissions are unchanged.
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
            html_body=html_body,
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
