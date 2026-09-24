from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Iterable, Iterator

from .config import OutlookConfig, OutlookUnavailableError
from .formatting import split_addresses

OL_FOLDER_INBOX = 6
OL_FOLDER_SENT = 5
OL_FOLDER_DRAFTS = 16
OL_FOLDER_CALENDAR = 9

OL_TO, OL_CC, OL_BCC = 1, 2, 3
OL_MAIL_ITEM = 43
OL_APPOINTMENT_ITEM = 26

# PR_SENT_REPRESENTING_SMTP_ADDRESS. Exchange hands back an X500 DN from
# SenderEmailAddress, which is useless for replying, so read the SMTP property
# directly and only fall back when it is missing.
PR_SENDER_SMTP = "http://schemas.microsoft.com/mapi/proptag/0x5D01001E"
PR_RECIPIENT_SMTP = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"

IMPORTANCE = {0: "low", 1: "normal", 2: "high"}

# OlBusyStatus. "free" is what a declined-but-kept or informational block looks
# like, so it is worth distinguishing from a meeting that actually cost time.
BUSY_STATUS = {0: "free", 1: "tentative", 2: "busy", 3: "out_of_office", 4: "working_elsewhere"}

OL_REQUIRED, OL_OPTIONAL = 1, 2

_com_state = threading.local()


def _ensure_com() -> None:
    """Initialise COM once per thread.

    MCP tool calls can land on different worker threads, and COM demands
    per-thread initialisation. Getting this wrong surfaces as a confusing
    "CoInitialize has not been called" deep inside pywin32.
    """
    if getattr(_com_state, "ready", False):
        return
    try:
        import pythoncom
    except ImportError as exc:  # pragma: no cover - Windows only
        raise OutlookUnavailableError(
            "pywin32 is not installed, so Outlook cannot be reached. Install it with "
            "'pip install pywin32'."
        ) from exc
    try:
        pythoncom.CoInitialize()
    except Exception:  # already initialised on this thread is fine
        pass
    _com_state.ready = True


def _safe(getter, default=None):
    """COM property access fails routinely on odd items; treat that as missing."""
    try:
        return getter()
    except Exception:
        return default


def _as_int(value: Any, default: int) -> int:
    """Coerce a COM numeric property, preserving a legitimate zero.

    ``int(x or default)`` is the obvious spelling and is wrong: enum values
    like olFree are 0, which is falsy, so the default silently wins.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_iso(value: Any) -> str:
    if value is None:
        return ""
    for attempt in (lambda: value.isoformat(), lambda: str(value)):
        result = _safe(attempt)
        if result:
            return str(result)
    return ""


class OutlookClient:
    """Thin, defensive wrapper over the Outlook COM object model.

    `app` is injectable purely so the logic above COM can be tested without
    Outlook installed; nothing else should pass it.
    """

    def __init__(self, config: OutlookConfig, app: Any | None = None) -> None:
        self.config = config
        self._app = app
        self._namespace: Any | None = None

    # ---------------------------------------------------------------- plumbing

    @property
    def app(self) -> Any:
        if self._app is None:
            _ensure_com()
            try:
                import win32com.client
            except ImportError as exc:  # pragma: no cover - Windows only
                raise OutlookUnavailableError(
                    "pywin32 is not installed, so Outlook cannot be reached."
                ) from exc
            try:
                self._app = win32com.client.Dispatch("Outlook.Application")
            except Exception as exc:
                raise OutlookUnavailableError(
                    f"Could not start or attach to Outlook: {exc}. Outlook must be installed "
                    "and the classic desktop client (not the new Outlook) is required, since "
                    "only it exposes COM."
                ) from exc
        return self._app

    @property
    def namespace(self) -> Any:
        if self._namespace is None:
            self._namespace = self.app.GetNamespace("MAPI")
        return self._namespace

    def health(self) -> dict[str, Any]:
        stores = [name for name, _ in self._root_folders()]
        return {
            "outlook_version": _safe(lambda: str(self.app.Version), "unknown"),
            "stores": stores,
            "default_account": _safe(
                lambda: str(self.namespace.Accounts.Item(1).SmtpAddress), ""
            ),
        }

    # ----------------------------------------------------------------- folders

    def _root_folders(self) -> list[tuple[str, Any]]:
        roots: list[tuple[str, Any]] = []
        folders = self.namespace.Folders
        for index in range(1, int(folders.Count) + 1):
            folder = _safe(lambda i=index: folders.Item(i))
            if folder is None:
                continue
            name = str(_safe(lambda f=folder: f.Name, "") or "")
            if self.config.store_name and name != self.config.store_name:
                continue
            roots.append((name, folder))
        return roots

    def iter_folders(self, max_depth: int = 4) -> Iterator[dict[str, Any]]:
        for name, root in self._root_folders():
            yield from self._walk(root, name, depth=0, max_depth=max_depth)

    def _walk(self, folder: Any, path: str, depth: int, max_depth: int) -> Iterator[dict[str, Any]]:
        yield {
            "path": path,
            "name": str(_safe(lambda: folder.Name, "") or ""),
            "items": int(_safe(lambda: folder.Items.Count, 0) or 0),
            "unread": int(_safe(lambda: folder.UnReadItemCount, 0) or 0),
        }
        if depth >= max_depth:
            return
        children = _safe(lambda: folder.Folders)
        if children is None:
            return
        count = int(_safe(lambda: children.Count, 0) or 0)
        for index in range(1, count + 1):
            child = _safe(lambda i=index: children.Item(i))
            if child is None:
                continue
            child_name = str(_safe(lambda c=child: c.Name, "") or "")
            yield from self._walk(child, f"{path}/{child_name}", depth + 1, max_depth)

    def resolve_folder(self, path: str) -> Any:
        """Find a folder by path, or fall back to the default Inbox.

        Accepts 'Inbox', 'Sent Items', 'Store/Folder/Sub', or either slash.
        """
        cleaned = (path or "").strip().replace("\\", "/").strip("/")
        if not cleaned or cleaned.lower() == "inbox":
            return self.namespace.GetDefaultFolder(OL_FOLDER_INBOX)
        lowered = cleaned.lower()
        if lowered in ("sent", "sent items"):
            return self.namespace.GetDefaultFolder(OL_FOLDER_SENT)
        if lowered == "drafts":
            return self.namespace.GetDefaultFolder(OL_FOLDER_DRAFTS)

        parts = cleaned.split("/")
        for store_name, root in self._root_folders():
            # The store name is optional, so try both with and without it.
            for candidate in ([parts[1:]] if parts[0] == store_name else []) + [parts]:
                if not candidate:
                    continue
                found = self._descend(root, candidate)
                if found is not None:
                    return found
        raise OutlookUnavailableError(
            f"No mail folder matches {path!r}. Call list_folders() to see the available paths."
        )

    def _descend(self, folder: Any, parts: list[str]) -> Any | None:
        current = folder
        for part in parts:
            children = _safe(lambda c=current: c.Folders)
            if children is None:
                return None
            count = int(_safe(lambda: children.Count, 0) or 0)
            match = None
            for index in range(1, count + 1):
                child = _safe(lambda i=index: children.Item(i))
                if child is None:
                    continue
                if str(_safe(lambda c=child: c.Name, "") or "").lower() == part.lower():
                    match = child
                    break
            if match is None:
                return None
            current = match
        return current

    # ---------------------------------------------------------------- reading

    def _folder_path(self, folder: Any) -> str:
        parts: list[str] = []
        current = folder
        for _ in range(12):  # bounded: a cycle here would hang the server
            if current is None:
                break
            name = _safe(lambda c=current: c.Name)
            if not name:
                break
            parts.append(str(name))
            current = _safe(lambda c=current: c.Parent)
        return "/".join(reversed(parts))

    def _recipients(self, item: Any) -> tuple[list[str], list[str]]:
        to: list[str] = []
        cc: list[str] = []
        recipients = _safe(lambda: item.Recipients)
        count = int(_safe(lambda: recipients.Count, 0) or 0) if recipients else 0
        for index in range(1, count + 1):
            recipient = _safe(lambda i=index: recipients.Item(i))
            if recipient is None:
                continue
            address = _safe(
                lambda r=recipient: r.PropertyAccessor.GetProperty(PR_RECIPIENT_SMTP)
            ) or _safe(lambda r=recipient: r.Address, "")
            label = str(_safe(lambda r=recipient: r.Name, "") or "")
            entry = f"{label} <{address}>" if address and label else (label or str(address or ""))
            kind = int(_safe(lambda r=recipient: r.Type, OL_TO) or OL_TO)
            (cc if kind == OL_CC else to).append(entry)
        if not to and not cc:
            to = split_addresses(str(_safe(lambda: item.To, "") or ""))
            cc = split_addresses(str(_safe(lambda: item.CC, "") or ""))
        return to, cc

    def _sender_email(self, item: Any) -> str:
        address = _safe(lambda: item.PropertyAccessor.GetProperty(PR_SENDER_SMTP))
        if address:
            return str(address)
        if str(_safe(lambda: item.SenderEmailType, "") or "").upper() == "EX":
            resolved = _safe(lambda: item.Sender.GetExchangeUser().PrimarySmtpAddress)
            if resolved:
                return str(resolved)
        return str(_safe(lambda: item.SenderEmailAddress, "") or "")

    def item_to_raw(self, item: Any, folder_path: str = "") -> dict[str, Any]:
        to, cc = self._recipients(item)
        html_body = _safe(lambda: item.HTMLBody, "") or ""
        plain_body = _safe(lambda: item.Body, "") or ""
        use_html = bool(html_body) and not plain_body
        attachments = _safe(lambda: item.Attachments)
        names: list[str] = []
        attachment_count = int(_safe(lambda: attachments.Count, 0) or 0) if attachments else 0
        for index in range(1, attachment_count + 1):
            name = _safe(lambda i=index: attachments.Item(i).FileName)
            if name:
                names.append(str(name))
        return {
            "entry_id": str(_safe(lambda: item.EntryID, "") or ""),
            "subject": str(_safe(lambda: item.Subject, "") or ""),
            "sender_name": str(_safe(lambda: item.SenderName, "") or ""),
            "sender_email": self._sender_email(item),
            "to": to,
            "cc": cc,
            "received": _to_iso(_safe(lambda: item.ReceivedTime)),
            "unread": bool(_safe(lambda: item.UnRead, False)),
            "has_attachments": bool(names),
            "attachments": names,
            "folder": folder_path or self._folder_path(_safe(lambda: item.Parent)),
            "importance": IMPORTANCE.get(int(_safe(lambda: item.Importance, 1) or 1), "normal"),
            "conversation_id": str(_safe(lambda: item.ConversationID, "") or ""),
            "body": html_body if use_html else plain_body,
            "is_html": use_html,
        }

    # ---------------------------------------------------------------- calendar

    def _attendees(self, item: Any) -> tuple[list[str], list[str]]:
        """Split an appointment's recipients into required and optional."""
        required: list[str] = []
        optional: list[str] = []
        recipients = _safe(lambda: item.Recipients)
        count = int(_safe(lambda: recipients.Count, 0) or 0) if recipients else 0
        for index in range(1, count + 1):
            recipient = _safe(lambda i=index: recipients.Item(i))
            if recipient is None:
                continue
            label = str(_safe(lambda r=recipient: r.Name, "") or "")
            if not label:
                continue
            kind = int(_safe(lambda r=recipient: r.Type, OL_REQUIRED) or OL_REQUIRED)
            (optional if kind == OL_OPTIONAL else required).append(label)
        if not required and not optional:
            required = split_addresses(str(_safe(lambda: item.RequiredAttendees, "") or ""))
            optional = split_addresses(str(_safe(lambda: item.OptionalAttendees, "") or ""))
        return required, optional

    def event_to_raw(self, item: Any) -> dict[str, Any]:
        html_body = _safe(lambda: item.HTMLBody, "") or ""
        plain_body = _safe(lambda: item.Body, "") or ""
        use_html = bool(html_body) and not plain_body
        required, optional = self._attendees(item)
        categories = [
            part.strip()
            for part in str(_safe(lambda: item.Categories, "") or "").split(",")
            if part.strip()
        ]
        return {
            "entry_id": str(_safe(lambda: item.EntryID, "") or ""),
            "subject": str(_safe(lambda: item.Subject, "") or ""),
            "start": _to_iso(_safe(lambda: item.Start)),
            "end": _to_iso(_safe(lambda: item.End)),
            "duration_minutes": _as_int(_safe(lambda: item.Duration), 0),
            "organizer": str(_safe(lambda: item.Organizer, "") or ""),
            "required": required,
            "optional": optional,
            "location": str(_safe(lambda: item.Location, "") or ""),
            "categories": categories,
            "is_recurring": bool(_safe(lambda: item.IsRecurring, False)),
            # Not `... or 2`: olFree is 0, and `0 or 2` would silently relabel
            # every free block as busy.
            "busy_status": BUSY_STATUS.get(
                _as_int(_safe(lambda: item.BusyStatus), 2), "busy"
            ),
            "all_day": bool(_safe(lambda: item.AllDayEvent, False)),
            "body": html_body if use_html else plain_body,
            "is_html": use_html,
        }

    def list_events(
        self,
        days_back: int = 7,
        days_forward: int = 0,
        limit: int = 50,
        include_all_day: bool = True,
        busy_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List calendar appointments in a window around today, earliest first.

        Recurring meetings are the whole point of a work calendar and they are
        also the easy thing to get wrong: Outlook stores one master item per
        series, so unless ``IncludeRecurrences`` is set *and* the collection is
        sorted by ``[Start]`` **before** ``Restrict`` is applied, every weekly
        standup silently vanishes from the result.

        ``busy_only`` drops only free blocks, which is what cancelled meetings
        report as. Tentative is deliberately kept: see the comment below.
        """
        folder = _safe(lambda: self.namespace.GetDefaultFolder(OL_FOLDER_CALENDAR))
        if folder is None:
            raise OutlookUnavailableError("Could not open the default Calendar folder.")
        items = folder.Items
        _safe(lambda: setattr(items, "IncludeRecurrences", True))
        _safe(lambda: items.Sort("[Start]"))

        start = datetime.now() - timedelta(days=max(0, days_back))
        end = datetime.now() + timedelta(days=max(0, days_forward) + 1)
        # Outlook's Restrict parser wants US-style dates regardless of locale.
        low = start.strftime("%m/%d/%Y %I:%M %p")
        high = end.strftime("%m/%d/%Y %I:%M %p")
        items = _safe(
            lambda: items.Restrict(f"[Start] >= '{low}' AND [Start] <= '{high}'"),
            items,
        )

        out: list[dict[str, Any]] = []
        # Bounded scan, same reasoning as list_raw: a calendar with years of
        # history must not turn one tool call into a full-store walk.
        scan_cap = max(limit * 20, 200)
        count = int(_safe(lambda: items.Count, 0) or 0)
        for index in range(1, min(count, scan_cap) + 1):
            if len(out) >= limit:
                break
            item = _safe(lambda i=index: items.Item(i))
            if item is None:
                continue
            # Default 0 so an item whose Class read fails is skipped rather
            # than emitted with every field blank.
            if int(_safe(lambda: item.Class, 0) or 0) != OL_APPOINTMENT_ITEM:
                continue
            if not str(_safe(lambda: item.EntryID, "") or "").strip():
                continue
            raw = _safe(lambda i=item: self.event_to_raw(i))
            if not raw:
                continue
            if not include_all_day and raw.get("all_day"):
                continue
            # Only "free" is dropped, never "tentative". In a real mailbox
            # tentative is the resting state of a perfectly normal accepted
            # meeting - people rarely click Accept - whereas cancelled
            # meetings reliably come back as free. Filtering tentative here
            # silently threw away most of the working week.
            if busy_only and raw.get("busy_status") == "free":
                continue
            out.append(raw)
        out.sort(key=lambda raw: str(raw.get("start") or ""))
        return out

    def list_raw(
        self,
        folder_path: str = "",
        limit: int = 25,
        unread_only: bool = False,
        days: int = 0,
        from_contains: str = "",
        subject_contains: str = "",
        stats: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        folder = self.resolve_folder(folder_path)
        resolved_path = self._folder_path(folder)
        items = folder.Items

        if days > 0:
            cutoff = datetime.now() - timedelta(days=days)
            # Outlook's Restrict parser wants US-style dates regardless of locale.
            stamp = cutoff.strftime("%m/%d/%Y %I:%M %p")
            items = _safe(lambda: items.Restrict(f"[ReceivedTime] >= '{stamp}'"), items)
        if unread_only:
            items = _safe(lambda: items.Restrict("[UnRead] = True"), items)
        # Sort last, never before Restrict: Restrict returns a *new* collection
        # that does not inherit the sort, so sorting first quietly handed back
        # an arbitrary subset instead of the newest mail.
        _safe(lambda: items.Sort("[ReceivedTime]", True))

        needle_from = from_contains.lower().strip()
        needle_subject = subject_contains.lower().strip()

        results: list[dict[str, Any]] = []
        # Bounded scan: a big mailbox must not turn one tool call into a
        # full-store walk, so stop well before exhausting the folder.
        scan_cap = max(limit * 20, 200)
        count = int(_safe(lambda: items.Count, 0) or 0)
        scanned = 0
        hit_limit = False
        for index in range(1, min(count, scan_cap) + 1):
            scanned = index
            item = _safe(lambda i=index: items.Item(i))
            if item is None:
                continue
            # Default 0, not OL_MAIL_ITEM: an item whose Class read *fails* is
            # exactly the corrupt/non-mail kind we want to skip. Defaulting to
            # "mail" let those through and emitted an entry with every field
            # blank, because every other property read failed too.
            if int(_safe(lambda: item.Class, 0) or 0) != OL_MAIL_ITEM:
                continue
            # A mail with no entry id cannot be fetched or acted on later, so
            # reporting it would only be noise.
            if not str(_safe(lambda: item.EntryID, "") or "").strip():
                continue
            if needle_subject and needle_subject not in str(
                _safe(lambda: item.Subject, "") or ""
            ).lower():
                continue
            if needle_from:
                haystack = (
                    str(_safe(lambda: item.SenderName, "") or "")
                    + " "
                    + self._sender_email(item)
                ).lower()
                if needle_from not in haystack:
                    continue
            results.append(self.item_to_raw(item, resolved_path))
            if len(results) >= limit:
                hit_limit = True
                break
        if stats is not None:
            # Two different reasons the caller may be seeing a partial answer:
            # the result limit was reached, or the bounded scan gave up before
            # the end of the folder. Both used to be invisible.
            stats["scanned"] = scanned
            stats["folder_items"] = count
            stats["hit_limit"] = hit_limit
            stats["scan_incomplete"] = not hit_limit and scanned < count
            stats["more_available"] = hit_limit or stats["scan_incomplete"]
        return results

    def get_raw(self, entry_id: str) -> dict[str, Any]:
        item = _safe(lambda: self.namespace.GetItemFromID(entry_id))
        if item is None:
            raise OutlookUnavailableError(
                f"No mail item with entry_id {entry_id!r}. Entry ids come from list_messages "
                "and change if an item is moved between stores."
            )
        return self.item_to_raw(item)

    def mark_read(self, entry_id: str, read: bool = True) -> dict[str, Any]:
        item = _safe(lambda: self.namespace.GetItemFromID(entry_id))
        if item is None:
            raise OutlookUnavailableError(f"No mail item with entry_id {entry_id!r}.")
        item.UnRead = not read
        item.Save()
        return {"entry_id": entry_id, "unread": not read}

    # ---------------------------------------------------------------- writing

    def _compose(
        self,
        to: Iterable[str],
        subject: str,
        body: str,
        cc: Iterable[str] = (),
        bcc: Iterable[str] = (),
    ) -> Any:
        mail = self.app.CreateItem(0)
        mail.To = "; ".join(to)
        if cc:
            mail.CC = "; ".join(cc)
        if bcc:
            mail.BCC = "; ".join(bcc)
        mail.Subject = subject
        mail.Body = body
        return mail

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
    ) -> dict[str, Any]:
        mail = self._compose(
            split_addresses(to), subject, body, split_addresses(cc), split_addresses(bcc)
        )
        mail.Save()
        return {
            "saved": True,
            "sent": False,
            "entry_id": str(_safe(lambda: mail.EntryID, "") or ""),
            "to": split_addresses(to),
            "subject": subject,
            "where": "Outlook Drafts folder - open Outlook to review and send.",
        }

    def send_mail(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
    ) -> dict[str, Any]:
        recipients = split_addresses(to)
        mail = self._compose(
            recipients, subject, body, split_addresses(cc), split_addresses(bcc)
        )
        mail.Send()
        return {
            "sent": True,
            "to": recipients,
            "cc": split_addresses(cc),
            "subject": subject,
            "posted_as": "your own Outlook account - recipients cannot tell it was drafted",
        }

    def reply(
        self,
        entry_id: str,
        body: str,
        reply_all: bool = False,
        send: bool = False,
        subject: str = "",
    ) -> dict[str, Any]:
        item = _safe(lambda: self.namespace.GetItemFromID(entry_id))
        if item is None:
            raise OutlookUnavailableError(f"No mail item with entry_id {entry_id!r}.")
        draft = item.ReplyAll() if reply_all else item.Reply()
        # Prepend so Outlook's quoted original stays underneath, as in a normal reply.
        draft.Body = body + "\n\n" + str(_safe(lambda: draft.Body, "") or "")
        # Outlook forces "RE: <original>", which is wrong for a rolling series
        # like a weekly report where the subject carries a changing week number.
        if subject.strip():
            draft.Subject = subject.strip()
        if send:
            draft.Send()
            return {
                "sent": True,
                "reply_all": reply_all,
                "subject": str(_safe(lambda: draft.Subject, "") or ""),
                "posted_as": "your own Outlook account",
            }
        draft.Save()
        return {
            "sent": False,
            "saved": True,
            "reply_all": reply_all,
            "entry_id": str(_safe(lambda: draft.EntryID, "") or ""),
            "subject": str(_safe(lambda: draft.Subject, "") or ""),
            "where": "Outlook Drafts folder - open Outlook to review and send.",
        }
