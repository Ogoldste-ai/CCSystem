from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from outlook_mcp.config import (  # noqa: E402
    OutlookConfig,
    OutlookUnavailableError,
    OutlookWriteDisabledError,
)
from outlook_mcp.formatting import (  # noqa: E402
    cap_recipients,
    clean_text,
    html_to_text,
    preview_of,
    shape_body,
    split_addresses,
    strip_quoted_history,
    truncate,
)
from outlook_mcp.models import MailMessage  # noqa: E402
from outlook_mcp.outlook import PR_RECIPIENT_SMTP, PR_SENDER_SMTP, OutlookClient  # noqa: E402
from outlook_mcp.server import build_server  # noqa: E402


# --------------------------------------------------------------------- fakes


class FakeCollection:
    def __init__(self, items):
        self._items = list(items)

    @property
    def Count(self):
        return len(self._items)

    def Item(self, index):
        return self._items[index - 1]


class FakeProperties:
    def __init__(self, values):
        self._values = values

    def GetProperty(self, name):
        if name in self._values:
            return self._values[name]
        raise RuntimeError(f"property {name} not available")


class FakeRecipient:
    def __init__(self, name, smtp, kind=1, address=""):
        self.Name = name
        self.Type = kind
        self.Address = address or smtp
        self.PropertyAccessor = FakeProperties({PR_RECIPIENT_SMTP: smtp})


class FakeMail:
    Class = 43
    Importance = 1

    def __init__(
        self,
        entry_id,
        subject,
        sender_name="Someone",
        smtp="someone@example.com",
        body="",
        html_body="",
        received=None,
        unread=False,
        recipients=(),
        attachments=(),
        conversation_id="",
    ):
        self.EntryID = entry_id
        self.Subject = subject
        self.SenderName = sender_name
        self.SenderEmailAddress = "/O=EXCH/CN=BROKEN"
        self.SenderEmailType = "EX"
        self.Body = body
        self.HTMLBody = html_body
        self.ReceivedTime = received or datetime(2026, 9, 14, 12, 0, 0)
        self.UnRead = unread
        self.ConversationID = conversation_id
        self.To = ""
        self.CC = ""
        self.Parent = None
        self.Recipients = FakeCollection(recipients)
        self.Attachments = FakeCollection(
            [type("A", (), {"FileName": name})() for name in attachments]
        )
        self.PropertyAccessor = FakeProperties({PR_SENDER_SMTP: smtp})
        self.saved = False
        self.sent = False
        self.replied_all = None

    def Save(self):
        self.saved = True

    def Send(self):
        self.sent = True

    def Reply(self):
        return self._make_reply(False)

    def ReplyAll(self):
        return self._make_reply(True)

    def _make_reply(self, all_):
        draft = FakeMail("reply-1", f"RE: {self.Subject}", body="\n> original text")
        draft.replied_all = all_
        self.last_reply = draft
        return draft


class FakeAppointment:
    Class = 26

    def __init__(
        self,
        entry_id,
        subject,
        start,
        duration=60,
        organizer="Oren Goldstein",
        required=(),
        optional=(),
        location="",
        categories="",
        is_recurring=False,
        busy_status=2,
        all_day=False,
        body="",
    ):
        self.EntryID = entry_id
        self.Subject = subject
        self.Start = start
        self.End = start + timedelta(minutes=duration)
        self.Duration = duration
        self.Organizer = organizer
        self.Location = location
        self.Categories = categories
        self.IsRecurring = is_recurring
        self.BusyStatus = busy_status
        self.AllDayEvent = all_day
        self.Body = body
        self.HTMLBody = ""
        self.RequiredAttendees = ""
        self.OptionalAttendees = ""
        self.Recipients = FakeCollection(
            [FakeRecipient(n, f"{n.lower()}@nuvoton.com", 1) for n in required]
            + [FakeRecipient(n, f"{n.lower()}@nuvoton.com", 2) for n in optional]
        )
        self.Parent = None


class FakeItems:
    def __init__(self, items):
        self._items = list(items)
        # Real Outlook returns a *new* collection from Restrict that does not
        # inherit a previously applied Sort. Model that from the unsorted
        # original, or the sort-before-restrict bug is invisible in tests.
        self._original = list(items)
        # Outlook only expands a recurring series when this is set. Default
        # False so a client that forgets to set it sees only masters, exactly
        # as it would against the real object model.
        self.IncludeRecurrences = False

    @property
    def Count(self):
        return len(self._items)

    def Item(self, index):
        return self._items[index - 1]

    def Sort(self, field, descending=False):
        key = (
            (lambda m: m.Start)
            if "Start" in str(field)
            else (lambda m: m.ReceivedTime)
        )
        self._items.sort(key=key, reverse=descending)

    def Restrict(self, query):
        if "UnRead" in query:
            return FakeItems([m for m in self._original if m.UnRead])
        out = FakeItems(self._original)
        # Restrict returns a new collection, but the recurrence setting is a
        # property of the *source* collection and its effect carries into the
        # restricted result. Propagate it so a client that sets the flag after
        # restricting is correctly shown as broken.
        out.IncludeRecurrences = self.IncludeRecurrences
        if not out.IncludeRecurrences:
            out._items = [m for m in out._items if not getattr(m, "IsRecurring", False)]
        return out


class FakeFolder:
    def __init__(self, name, items=(), children=()):
        self.Name = name
        self._items = FakeItems(items)
        self._children = list(children)
        self.Parent = None
        for child in self._children:
            child.Parent = self
        for item in items:
            item.Parent = self

    @property
    def Items(self):
        return self._items

    @property
    def Folders(self):
        return FakeCollection(self._children)

    @property
    def UnReadItemCount(self):
        return sum(1 for item in self._items._items if item.UnRead)


class FakeNamespace:
    def __init__(self, roots, defaults=None, by_id=None):
        self._roots = list(roots)
        self._defaults = defaults or {}
        self._by_id = by_id or {}
        self.Accounts = FakeCollection([type("Acct", (), {"SmtpAddress": "me@nuvoton.com"})()])

    @property
    def Folders(self):
        return FakeCollection(self._roots)

    def GetDefaultFolder(self, index):
        return self._defaults[index]

    def GetItemFromID(self, entry_id):
        if entry_id not in self._by_id:
            raise RuntimeError("not found")
        return self._by_id[entry_id]


class FakeApp:
    Version = "16.0.0"

    def __init__(self, namespace):
        self._namespace = namespace
        self.created = []

    def GetNamespace(self, name):
        return self._namespace

    def CreateItem(self, kind):
        mail = FakeMail("draft-1", "")
        self.created.append(mail)
        return mail


def build_client(allow_write=False, allow_send=True, preview_chars=400):
    inbox_items = [
        FakeMail(
            "id-1",
            "Build broke on master",
            sender_name="Itamar Tamir",
            smtp="itamar.tamir@nuvoton.com",
            body="The pipeline is red.\n\nFrom: someone\n> old quoted stuff",
            received=datetime.now() - timedelta(hours=1),
            unread=True,
            recipients=[FakeRecipient("Oren", "ogoldste@nuvoton.com", 1)],
            attachments=["log.txt"],
        ),
        FakeMail(
            "id-2",
            "Lunch?",
            sender_name="Shir",
            smtp="shir@nuvoton.com",
            body="Are you free at 12?",
            received=datetime.now() - timedelta(days=10),
            recipients=[
                FakeRecipient("Oren", "ogoldste@nuvoton.com", 1),
                FakeRecipient("Team", "team@nuvoton.com", 2),
            ],
        ),
    ]
    sub = FakeFolder("Projects", items=[FakeMail("id-3", "Spec review")])
    inbox = FakeFolder("Inbox", items=inbox_items, children=[sub])
    sent = FakeFolder("Sent Items", items=[FakeMail("id-4", "Re: Spec review")])
    calendar_items = [
        FakeAppointment(
            "appt-1",
            "EC I3C design review",
            datetime.now() - timedelta(days=2),
            duration=90,
            required=["Itamar"],
            optional=["Shir"],
            location="Room 4",
            categories="EC, Review",
            body="Walk through the I3C host changes.",
        ),
        FakeAppointment(
            "appt-2",
            "Weekly team standup",
            datetime.now() - timedelta(days=1),
            duration=30,
            is_recurring=True,
        ),
        FakeAppointment(
            "appt-3",
            "Focus block",
            datetime.now() - timedelta(days=3),
            duration=120,
            busy_status=0,
        ),
        FakeAppointment(
            "appt-4",
            "Company holiday",
            datetime.now() - timedelta(days=4),
            all_day=True,
        ),
        FakeAppointment(
            "appt-5",
            "Tentative design sync",
            datetime.now() - timedelta(days=2),
            duration=45,
            busy_status=1,
        ),
    ]
    calendar = FakeFolder("Calendar", items=calendar_items)
    root = FakeFolder("me@nuvoton.com", children=[inbox, sent])
    namespace = FakeNamespace(
        [root],
        defaults={6: inbox, 5: sent, 16: FakeFolder("Drafts"), 9: calendar},
        by_id={item.EntryID: item for item in inbox_items},
    )
    app = FakeApp(namespace)
    config = OutlookConfig(
        allow_write=allow_write, allow_send=allow_send, preview_chars=preview_chars
    )
    return OutlookClient(config, app=app), config, app


def tools_of(server):
    return {name: server._tool_manager.get_tool(name).fn for name in
            [t.name for t in server._tool_manager.list_tools()]}


# ---------------------------------------------------------------- formatting


def test_html_to_text_flattens_markup_and_entities():
    html = "<div><p>Hello <b>there</b></p><p>Second &amp; last</p></div>"
    assert html_to_text(html) == "Hello there\n\nSecond & last"


def test_html_to_text_drops_script_and_style_content():
    html = "<style>.a{color:red}</style><p>Visible</p><script>evil()</script>"
    assert "color" not in html_to_text(html)
    assert "evil" not in html_to_text(html)
    assert "Visible" in html_to_text(html)


def test_html_to_text_handles_empty():
    assert html_to_text("") == ""


def test_clean_text_collapses_long_blank_runs():
    assert clean_text("a\n\n\n\n\nb") == "a\n\nb"


def test_clean_text_normalises_crlf_and_nbsp():
    assert clean_text("a\r\nb\xa0c") == "a\nb c"


def test_strip_quoted_history_cuts_at_the_marker():
    body = "My actual reply.\n\nFrom: Someone\n> older text"
    assert strip_quoted_history(body) == "My actual reply."


def test_strip_quoted_history_keeps_body_when_marker_is_at_the_start():
    # The whole message is quoted; returning nothing would be worse than this.
    body = "From: Someone\n> everything is quoted"
    assert strip_quoted_history(body) == body


def test_truncate_marks_when_it_cut():
    text, cut = truncate("x" * 100, 10)
    assert cut is True
    assert text.endswith("...")


def test_truncate_leaves_short_text_alone():
    assert truncate("short", 100) == ("short", False)


def test_truncate_with_zero_limit_is_a_passthrough():
    assert truncate("anything", 0) == ("anything", False)


def test_truncate_prefers_a_word_boundary():
    text, _ = truncate("alpha beta gamma delta", 18)
    assert not text.replace(" ...", "").endswith("del")


def test_preview_of_flattens_html_and_truncates():
    preview, cut = preview_of("<p>" + "word " * 100 + "</p>", True, 50)
    assert cut is True
    assert "<p>" not in preview


def test_split_addresses_handles_both_separators():
    assert split_addresses("a@x.com; b@x.com, c@x.com") == [
        "a@x.com",
        "b@x.com",
        "c@x.com",
    ]


def test_split_addresses_of_empty_is_empty():
    assert split_addresses("") == []


# Regression: a 50-recipient mail made list output unreadably large.


def test_cap_recipients_keeps_the_head_and_counts_the_rest():
    values = [f"p{n}@x.com" for n in range(10)]
    assert cap_recipients(values, 3) == ["p0@x.com", "p1@x.com", "p2@x.com", "+7 more"]


def test_cap_recipients_leaves_short_lists_untouched():
    assert cap_recipients(["a@x.com", "b@x.com"], 3) == ["a@x.com", "b@x.com"]


def test_cap_recipients_with_zero_limit_keeps_everything():
    values = [f"p{n}@x.com" for n in range(10)]
    assert cap_recipients(values, 0) == values


def test_cap_recipients_does_not_mutate_the_input():
    values = ["a@x.com", "b@x.com", "c@x.com", "d@x.com"]
    cap_recipients(values, 2)
    assert len(values) == 4


# Regression: one notification mail produced a 310,000 character body.


def test_shape_body_drops_quoted_history_and_reports_how_much():
    body, info = shape_body("My reply.\n\nFrom: Someone\n" + "q" * 5000)
    assert body == "My reply."
    assert info["quoted_history_chars_removed"] > 4000
    assert info["body_total_chars"] == len("My reply.")


def test_shape_body_keeps_quoted_history_when_asked():
    body, info = shape_body("My reply.\n\nFrom: Someone\nold", include_quoted=True)
    assert "From: Someone" in body
    assert "quoted_history_chars_removed" not in info


def test_shape_body_caps_length_and_offers_the_next_offset():
    body, info = shape_body("z" * 1000, include_quoted=True, limit=100)
    assert len(body) == 100
    assert info["body_truncated"] is True
    assert info["body_next_offset"] == 100
    assert info["body_total_chars"] == 1000


def test_shape_body_offset_reads_the_next_part():
    text = "abcdefghij" * 10
    body, info = shape_body(text, include_quoted=True, offset=50, limit=25)
    assert body == text[50:75]
    assert info["body_offset"] == 50
    assert info["body_next_offset"] == 75


def test_shape_body_final_chunk_is_not_flagged_truncated():
    _, info = shape_body("z" * 100, include_quoted=True, offset=50, limit=50)
    assert "body_truncated" not in info


def test_shape_body_offset_past_the_end_is_empty_not_an_error():
    body, info = shape_body("short", include_quoted=True, offset=9999)
    assert body == ""
    assert info["body_offset"] == len("short")


def test_shape_body_without_a_limit_returns_everything():
    body, info = shape_body("z" * 5000, include_quoted=True)
    assert len(body) == 5000
    assert "body_truncated" not in info


# -------------------------------------------------------------------- models


def test_message_preview_only_by_default_and_says_so():
    raw = {"entry_id": "e", "subject": "s", "body": "y" * 900, "is_html": False}
    data = MailMessage.from_raw(raw, preview_chars=50).to_dict()
    assert "body" not in data
    assert data["body_truncated"] is True
    assert "get_message" in data["hint"]


def test_message_full_body_is_not_flagged_as_truncated():
    raw = {"entry_id": "e", "subject": "s", "body": "y" * 900, "is_html": False}
    data = MailMessage.from_raw(raw, preview_chars=50, include_body=True).to_dict()
    assert data["body"]
    assert "body_truncated" not in data


def test_message_without_subject_gets_a_placeholder():
    assert MailMessage.from_raw({"entry_id": "e"}).subject == "(no subject)"


def test_message_omits_empty_optional_fields():
    data = MailMessage.from_raw({"entry_id": "e", "subject": "s"}).to_dict()
    assert "cc" not in data
    assert "attachments" not in data
    assert "importance" not in data


def test_message_caps_recipients_for_list_results():
    raw = {
        "entry_id": "e",
        "subject": "s",
        "to": [f"p{n}@x.com" for n in range(54)],
        "cc": [f"c{n}@x.com" for n in range(20)],
    }
    data = MailMessage.from_raw(raw).to_dict(max_recipients=3)
    assert data["to"][-1] == "+51 more"
    assert data["cc"][-1] == "+17 more"


def test_message_keeps_every_recipient_for_a_single_message():
    raw = {"entry_id": "e", "subject": "s", "to": [f"p{n}@x.com" for n in range(54)]}
    data = MailMessage.from_raw(raw, include_body=True).to_dict(max_recipients=0)
    assert len(data["to"]) == 54
    assert "more" not in data["to"][-1]


def test_message_body_is_capped_and_says_how_to_continue():
    raw = {"entry_id": "e", "subject": "s", "body": "z" * 5000, "is_html": False}
    data = MailMessage.from_raw(raw, include_body=True, max_body_chars=1000).to_dict()
    assert len(data["body"]) == 1000
    assert data["body_total_chars"] == 5000
    assert data["body_next_offset"] == 1000
    assert "body_offset=1000" in data["hint"]


def test_message_body_offset_continues_where_it_left_off():
    raw = {"entry_id": "e", "subject": "s", "body": "z" * 5000, "is_html": False}
    data = MailMessage.from_raw(
        raw, include_body=True, max_body_chars=1000, body_offset=1000
    ).to_dict()
    assert data["body_offset"] == 1000
    assert data["body_next_offset"] == 2000


def test_message_body_drops_the_quoted_chain_by_default():
    raw = {
        "entry_id": "e",
        "subject": "s",
        "body": "Please check this PR.\n\nFrom: GitHub\n" + "q" * 300000,
        "is_html": False,
    }
    data = MailMessage.from_raw(raw, include_body=True, max_body_chars=20000).to_dict()
    assert data["body"] == "Please check this PR."
    assert "include_quoted=True" in data["hint"]


# -------------------------------------------------------------------- config


def test_write_guard_blocks_and_explains_why():
    config = OutlookConfig(allow_write=False)
    with pytest.raises(OutlookWriteDisabledError) as excinfo:
        config.require_write()
    assert "OUTLOOK_ALLOW_WRITE" in str(excinfo.value)
    assert "cannot be unsent" in str(excinfo.value)


def test_send_guard_can_be_refused_separately_from_write():
    config = OutlookConfig(allow_write=True, allow_send=False)
    config.require_write()
    with pytest.raises(OutlookWriteDisabledError) as excinfo:
        config.require_send()
    assert "create_draft" in str(excinfo.value)


def test_send_allowed_when_both_flags_are_on():
    OutlookConfig(allow_write=True, allow_send=True).require_send()


def test_config_reads_and_clamps_env(monkeypatch):
    monkeypatch.setenv("OUTLOOK_PREVIEW_CHARS", "999999")
    monkeypatch.setenv("OUTLOOK_MAX_RESULTS", "0")
    monkeypatch.setenv("OUTLOOK_ALLOW_WRITE", "yes")
    config = OutlookConfig.from_env()
    assert config.preview_chars == 20000
    assert config.max_results == 1
    assert config.allow_write is True


def test_config_ignores_non_numeric_env(monkeypatch):
    monkeypatch.setenv("OUTLOOK_PREVIEW_CHARS", "lots")
    assert OutlookConfig.from_env().preview_chars == 400


def test_config_defaults_to_no_write(monkeypatch):
    monkeypatch.delenv("OUTLOOK_ALLOW_WRITE", raising=False)
    assert OutlookConfig.from_env().allow_write is False


# ------------------------------------------------------------- outlook client


def test_health_reports_stores_and_account():
    client, _, _ = build_client()
    info = client.health()
    assert info["stores"] == ["me@nuvoton.com"]
    assert info["default_account"] == "me@nuvoton.com"


def test_iter_folders_includes_nested_paths():
    client, _, _ = build_client()
    paths = [folder["path"] for folder in client.iter_folders()]
    assert "me@nuvoton.com/Inbox" in paths
    assert "me@nuvoton.com/Inbox/Projects" in paths


def test_iter_folders_reports_unread_counts():
    client, _, _ = build_client()
    inbox = next(f for f in client.iter_folders() if f["path"].endswith("/Inbox"))
    assert inbox["unread"] == 1


def test_resolve_folder_defaults_to_inbox():
    client, _, _ = build_client()
    assert client.resolve_folder("").Name == "Inbox"
    assert client.resolve_folder("Inbox").Name == "Inbox"


def test_resolve_folder_finds_a_nested_path_with_either_slash():
    client, _, _ = build_client()
    assert client.resolve_folder("Inbox/Projects").Name == "Projects"
    assert client.resolve_folder("Inbox\\Projects").Name == "Projects"


def test_resolve_folder_accepts_a_store_prefixed_path():
    client, _, _ = build_client()
    assert client.resolve_folder("me@nuvoton.com/Inbox/Projects").Name == "Projects"


def test_resolve_folder_error_points_at_list_folders():
    client, _, _ = build_client()
    with pytest.raises(OutlookUnavailableError) as excinfo:
        client.resolve_folder("Nope/Missing")
    assert "list_folders" in str(excinfo.value)


def test_sender_email_prefers_smtp_over_the_exchange_dn():
    client, _, _ = build_client()
    raw = client.list_raw(limit=10)[0]
    assert raw["sender_email"] == "itamar.tamir@nuvoton.com"
    assert "EXCH" not in raw["sender_email"]


def test_recipients_are_split_into_to_and_cc():
    client, _, _ = build_client()
    lunch = next(r for r in client.list_raw(limit=10) if r["subject"] == "Lunch?")
    assert any("ogoldste@nuvoton.com" in entry for entry in lunch["to"])
    assert any("team@nuvoton.com" in entry for entry in lunch["cc"])


def test_list_raw_sorts_newest_first():
    client, _, _ = build_client()
    subjects = [raw["subject"] for raw in client.list_raw(limit=10)]
    assert subjects[0] == "Build broke on master"


def test_list_raw_honours_the_limit():
    client, _, _ = build_client()
    assert len(client.list_raw(limit=1)) == 1


def test_list_raw_unread_only_filters():
    client, _, _ = build_client()
    results = client.list_raw(limit=10, unread_only=True)
    assert [raw["subject"] for raw in results] == ["Build broke on master"]


def test_list_raw_filters_by_subject_substring():
    client, _, _ = build_client()
    assert len(client.list_raw(limit=10, subject_contains="lunch")) == 1


def test_list_raw_filters_by_sender_substring():
    client, _, _ = build_client()
    results = client.list_raw(limit=10, from_contains="itamar")
    assert [raw["subject"] for raw in results] == ["Build broke on master"]


def test_list_raw_records_attachment_names():
    client, _, _ = build_client()
    raw = client.list_raw(limit=10)[0]
    assert raw["attachments"] == ["log.txt"]


# Regression: a non-mail item whose property reads all failed used to be
# reported as a mail with every field blank.


def test_list_raw_skips_items_whose_class_cannot_be_read():
    class HostileItem:
        """A corrupt item: every property read raises, including Class."""

        def __getattr__(self, name):
            raise RuntimeError(f"cannot read {name}")

    client, _, _ = build_client()
    inbox = client.resolve_folder("Inbox")
    inbox.Items._items.append(HostileItem())
    results = client.list_raw(limit=10)
    assert all(raw["entry_id"] for raw in results)
    assert all(raw["subject"] != "" for raw in results)


def test_list_raw_skips_non_mail_items():
    appointment = FakeMail("appt-1", "Team sync")
    appointment.Class = 26  # olAppointment
    client, _, _ = build_client()
    inbox = client.resolve_folder("Inbox")
    inbox.Items._items.append(appointment)
    subjects = [raw["subject"] for raw in client.list_raw(limit=10)]
    assert "Team sync" not in subjects


def test_list_raw_skips_mail_with_no_entry_id():
    ghost = FakeMail("", "Ghost item")
    client, _, _ = build_client()
    inbox = client.resolve_folder("Inbox")
    inbox.Items._items.append(ghost)
    subjects = [raw["subject"] for raw in client.list_raw(limit=10)]
    assert "Ghost item" not in subjects


def test_get_raw_missing_id_is_actionable():
    client, _, _ = build_client()
    with pytest.raises(OutlookUnavailableError) as excinfo:
        client.get_raw("nope")
    assert "list_messages" in str(excinfo.value)


def test_create_draft_saves_without_sending():
    client, _, app = build_client()
    result = client.create_draft(to="a@x.com; b@x.com", subject="Hi", body="Text")
    assert result["sent"] is False
    assert result["saved"] is True
    assert app.created[0].saved is True
    assert app.created[0].sent is False
    assert app.created[0].To == "a@x.com; b@x.com"


def test_send_mail_actually_sends_and_admits_the_identity():
    client, _, app = build_client()
    result = client.send_mail(to="a@x.com", subject="Hi", body="Text")
    assert result["sent"] is True
    assert app.created[0].sent is True
    assert "your own Outlook account" in result["posted_as"]


def test_reply_defaults_to_a_draft():
    client, _, _ = build_client()
    result = client.reply("id-1", "Thanks, looking now.")
    assert result["sent"] is False
    assert result["saved"] is True


def test_reply_keeps_the_quoted_original_underneath():
    client, _, ns = build_client()
    client.reply("id-1", "My answer")
    draft = ns.GetNamespace("MAPI").GetItemFromID("id-1").last_reply
    assert draft.Body.startswith("My answer")
    assert "original text" in draft.Body


def test_reply_all_is_distinct_from_reply():
    client, _, _ = build_client()
    assert client.reply("id-1", "x", reply_all=True)["reply_all"] is True


def test_reply_can_send_immediately():
    client, _, _ = build_client()
    assert client.reply("id-1", "x", send=True)["sent"] is True


def test_mark_read_updates_and_saves():
    client, _, _ = build_client()
    assert client.mark_read("id-1")["unread"] is False


# ------------------------------------------------------- reply subject override


def test_reply_keeps_outlooks_subject_by_default():
    client, _, ns = build_client()
    result = client.reply("id-1", "x", reply_all=True)
    assert result["subject"] == "RE: Build broke on master"


def test_reply_subject_override_replaces_the_re_prefix():
    """The whole point: a rolling series needs a changing subject, not RE:."""
    client, _, _ = build_client()
    result = client.reply("id-1", "x", reply_all=True, subject="Weekly - WW40")
    assert result["subject"] == "Weekly - WW40"


def test_reply_subject_override_is_trimmed():
    client, _, _ = build_client()
    result = client.reply("id-1", "x", subject="  Weekly - WW41  ")
    assert result["subject"] == "Weekly - WW41"


def test_reply_blank_subject_does_not_wipe_the_subject():
    client, _, _ = build_client()
    result = client.reply("id-1", "x", subject="   ")
    assert result["subject"] == "RE: Build broke on master"


def test_reply_subject_override_survives_an_immediate_send():
    client, _, _ = build_client()
    result = client.reply("id-1", "x", send=True, subject="Weekly - WW42")
    assert result["sent"] is True
    assert result["subject"] == "Weekly - WW42"


# -------------------------------------------------------------------- calendar


def test_list_events_returns_appointments_earliest_first():
    client, _, _ = build_client()
    events = client.list_events(days_back=7)
    starts = [e["start"] for e in events]
    assert starts == sorted(starts)
    assert {e["subject"] for e in events} >= {"EC I3C design review", "Focus block"}


def test_list_events_includes_recurring_occurrences():
    """Without IncludeRecurrences the weekly standup silently disappears."""
    client, _, _ = build_client()
    subjects = {e["subject"] for e in client.list_events(days_back=7)}
    assert "Weekly team standup" in subjects


def test_list_events_shapes_attendees_and_categories():
    client, _, _ = build_client()
    event = next(
        e for e in client.list_events(days_back=7) if e["subject"] == "EC I3C design review"
    )
    assert event["required"] == ["Itamar"]
    assert event["optional"] == ["Shir"]
    assert event["categories"] == ["EC", "Review"]
    assert event["location"] == "Room 4"
    assert event["duration_minutes"] == 90


def test_list_events_busy_only_drops_free_blocks():
    client, _, _ = build_client()
    subjects = {e["subject"] for e in client.list_events(days_back=7, busy_only=True)}
    assert "Focus block" not in subjects
    assert "EC I3C design review" in subjects


def test_list_events_busy_only_keeps_tentative_meetings():
    """Regression: real mailboxes leave accepted meetings marked tentative.

    Filtering tentative alongside free discarded almost every genuine meeting
    in the week, which is exactly the kind of silent emptiness a status mail
    must not be built on.
    """
    client, _, _ = build_client()
    subjects = {e["subject"] for e in client.list_events(days_back=7, busy_only=True)}
    assert "Tentative design sync" in subjects


def test_list_events_can_exclude_all_day_entries():
    client, _, _ = build_client()
    subjects = {
        e["subject"] for e in client.list_events(days_back=7, include_all_day=False)
    }
    assert "Company holiday" not in subjects


def test_list_events_respects_the_limit():
    client, _, _ = build_client()
    assert len(client.list_events(days_back=7, limit=2)) == 2


def test_list_calendar_events_tool_shapes_output():
    client, config, _ = build_client()
    rows = tools_of(build_server(config, client))["list_calendar_events"]()
    assert rows
    row = rows[0]
    assert "subject" in row and "start" in row and "busy_status" in row
    # An appointment has no sender or read state; those mail-only fields must
    # not leak into the calendar shape.
    assert "unread" not in row and "from" not in row


def test_list_calendar_events_tool_is_capped_by_max_results():
    client, config, _ = build_client()
    config.max_results = 1
    rows = tools_of(build_server(config, client))["list_calendar_events"](limit=50)
    assert len(rows) == 1


# -------------------------------------------------------------- server tools


def test_expected_tools_are_registered():
    client, config, _ = build_client()
    names = set(tools_of(build_server(config, client)))
    assert names == {
        "health",
        "list_folders",
        "list_messages",
        "get_message",
        "search_messages",
        "list_calendar_events",
        "mark_read",
        "create_draft",
        "send_mail",
        "reply_to_message",
    }


def test_health_reports_write_state():
    client, config, _ = build_client()
    info = tools_of(build_server(config, client))["health"]()
    assert info["status"] == "ok"
    assert info["write_enabled"] is False
    assert info["send_enabled"] is False


def test_list_messages_returns_previews_not_bodies():
    client, config, _ = build_client()
    rows = tools_of(build_server(config, client))["list_messages"]()
    assert rows and "preview" in rows[0]
    assert "body" not in rows[0]


def test_list_messages_preview_drops_the_quoted_chain():
    client, config, _ = build_client()
    rows = tools_of(build_server(config, client))["list_messages"]()
    top = next(r for r in rows if r["subject"] == "Build broke on master")
    assert "old quoted stuff" not in top["preview"]


def test_get_message_returns_the_full_body():
    client, config, _ = build_client()
    data = tools_of(build_server(config, client))["get_message"]("id-1")
    assert "The pipeline is red." in data["body"]


def test_get_message_strips_quoted_history_but_can_keep_it():
    client, config, _ = build_client()
    tools = tools_of(build_server(config, client))
    assert "old quoted stuff" not in tools["get_message"]("id-1")["body"]
    kept = tools["get_message"]("id-1", include_quoted=True)
    assert "old quoted stuff" in kept["body"]


def test_get_message_caps_a_huge_body_and_pages_through_it():
    client, config, _ = build_client()
    client.get_raw("id-1")  # entry exists
    huge = client.namespace.GetItemFromID("id-1")
    huge.Body = "z" * 50000
    config.max_body_chars = 1000
    tools = tools_of(build_server(config, client))

    first = tools["get_message"]("id-1")
    assert len(first["body"]) == 1000
    assert first["body_total_chars"] == 50000

    second = tools["get_message"]("id-1", body_offset=first["body_next_offset"])
    assert second["body_offset"] == 1000
    assert len(second["body"]) == 1000


def test_list_messages_caps_recipients_but_get_message_does_not():
    client, config, _ = build_client()
    item = client.namespace.GetItemFromID("id-2")
    item.Recipients = FakeCollection(
        [FakeRecipient(f"P{n}", f"p{n}@nuvoton.com", 1) for n in range(40)]
    )
    config.list_recipients = 3
    tools = tools_of(build_server(config, client))

    row = next(r for r in tools["list_messages"](limit=10) if r["subject"] == "Lunch?")
    assert row["to"][-1] == "+37 more"

    assert len(tools["get_message"]("id-2")["to"]) == 40


def test_limit_is_capped_by_max_results():
    client, config, _ = build_client()
    config.max_results = 1
    assert len(tools_of(build_server(config, client))["list_messages"](limit=99)) == 1


def test_search_matches_subject_or_sender():
    client, config, _ = build_client()
    tools = tools_of(build_server(config, client))
    assert tools["search_messages"]("lunch")[0]["subject"] == "Lunch?"
    assert tools["search_messages"]("itamar")[0]["subject"] == "Build broke on master"


def test_search_rejects_an_empty_query():
    client, config, _ = build_client()
    with pytest.raises(ValueError):
        tools_of(build_server(config, client))["search_messages"]("")


def test_send_mail_is_blocked_without_the_write_flag():
    client, config, app = build_client(allow_write=False)
    with pytest.raises(OutlookWriteDisabledError):
        tools_of(build_server(config, client))["send_mail"]("a@x.com", "s", "b")
    assert app.created == []


def test_create_draft_works_without_the_write_flag():
    # Drafts are recoverable and go nowhere on their own, so they stay ungated.
    client, config, app = build_client(allow_write=False)
    result = tools_of(build_server(config, client))["create_draft"]("a@x.com", "s", "b")
    assert result["saved"] is True
    assert app.created[0].sent is False


def test_reply_draft_allowed_but_sending_blocked_without_the_flag():
    client, config, _ = build_client(allow_write=False)
    tools = tools_of(build_server(config, client))
    assert tools["reply_to_message"]("id-1", "text")["sent"] is False
    with pytest.raises(OutlookWriteDisabledError):
        tools["reply_to_message"]("id-1", "text", send=True)


def test_mark_read_is_gated():
    client, config, _ = build_client(allow_write=False)
    with pytest.raises(OutlookWriteDisabledError):
        tools_of(build_server(config, client))["mark_read"]("id-1")


def test_send_mail_allowed_once_enabled():
    client, config, app = build_client(allow_write=True)
    result = tools_of(build_server(config, client))["send_mail"]("a@x.com", "s", "b")
    assert result["sent"] is True
    assert app.created[0].sent is True


def test_send_mail_rejects_empty_recipients_and_body():
    client, config, _ = build_client(allow_write=True)
    tools = tools_of(build_server(config, client))
    with pytest.raises(ValueError):
        tools["send_mail"]("", "s", "b")
    with pytest.raises(ValueError):
        tools["send_mail"]("a@x.com", "s", "   ")


# ------------------------------------------------- regressions: silent wrongness


def _folder_client(items, allow_write=False):
    """A client over one Inbox built from `items` in the given order."""
    inbox = FakeFolder("Inbox", items=items)
    root = FakeFolder("me@nuvoton.com", children=[inbox])
    namespace = FakeNamespace(
        [root],
        defaults={6: inbox, 5: FakeFolder("Sent Items"), 16: FakeFolder("Drafts")},
        by_id={item.EntryID: item for item in items},
    )
    config = OutlookConfig(allow_write=allow_write)
    return OutlookClient(config, app=FakeApp(namespace)), config


def _dated(entry_id, subject, hours_ago, unread=True):
    return FakeMail(
        entry_id,
        subject,
        body="body",
        received=datetime.now() - timedelta(hours=hours_ago),
        unread=unread,
    )


def test_list_raw_still_sorts_newest_first_after_a_days_restrict():
    # Stored oldest-first, so only a sort applied *after* Restrict can fix it.
    client, _ = _folder_client([_dated("old", "Older", 48), _dated("new", "Newer", 1)])
    subjects = [raw["subject"] for raw in client.list_raw(limit=10, days=7)]
    assert subjects == ["Newer", "Older"]


def test_list_raw_still_sorts_newest_first_after_an_unread_restrict():
    client, _ = _folder_client([_dated("old", "Older", 48), _dated("new", "Newer", 1)])
    subjects = [raw["subject"] for raw in client.list_raw(limit=10, unread_only=True)]
    assert subjects == ["Newer", "Older"]


def test_list_raw_reports_when_the_limit_hid_results():
    client, _ = _folder_client([_dated(f"m{i}", f"S{i}", i) for i in range(5)])
    stats = {}
    client.list_raw(limit=2, stats=stats)
    assert stats["hit_limit"] is True
    assert stats["more_available"] is True


def test_list_raw_reports_a_complete_scan_as_complete():
    client, _ = _folder_client([_dated(f"m{i}", f"S{i}", i) for i in range(3)])
    stats = {}
    client.list_raw(limit=25, stats=stats)
    assert stats["more_available"] is False
    assert stats["scan_incomplete"] is False


def test_list_messages_flags_a_partial_page():
    client, config = _folder_client([_dated(f"m{i}", f"S{i}", i) for i in range(5)])
    results = tools_of(build_server(config, client))["list_messages"](limit=2)
    assert len(results) == 2
    assert results[-1]["more_available"] is True
    assert "limit" in results[-1]["scan_hint"].lower()


def test_list_messages_does_not_flag_a_complete_page():
    client, config = _folder_client([_dated(f"m{i}", f"S{i}", i) for i in range(3)])
    results = tools_of(build_server(config, client))["list_messages"](limit=25)
    assert all("more_available" not in entry for entry in results)


def test_search_skips_the_second_scan_when_the_page_is_already_full():
    items = [_dated(f"m{i}", f"DV62 item {i}", i) for i in range(4)]
    client, config = _folder_client(items)
    calls = []
    original = client.list_raw

    def counting(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    client.list_raw = counting
    tools_of(build_server(config, client))["search_messages"]("DV62", limit=2)
    assert len(calls) == 1


def test_quoted_history_needs_a_real_attribution_not_a_bare_on():
    # "On " starting a line is ordinary prose and must not amputate the body.
    text = "Please review.\nOn the second point I disagree.\nThanks"
    assert strip_quoted_history(text) == text


def test_quoted_history_still_cuts_a_genuine_attribution():
    text = "Short answer.\nOn Mon, 8 Sep 2026 at 10:22, Arnon wrote:\n> the original"
    assert strip_quoted_history(text) == "Short answer."


def test_scan_hint_names_max_results_when_that_is_the_real_cap():
    client, config = _folder_client([_dated(f"m{i}", f"S{i}", i) for i in range(5)])
    config.max_results = 2
    results = tools_of(build_server(config, client))["list_messages"](limit=200)
    assert results[-1]["more_available"] is True
    assert "OUTLOOK_MAX_RESULTS" in results[-1]["scan_hint"]
    assert "you asked for 200" in results[-1]["scan_hint"]
