from __future__ import annotations

import sys
from datetime import date, datetime, time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from outlook_mcp.config import (  # noqa: E402
    OutlookConfig,
    OutlookUnavailableError,
    OutlookWriteDisabledError,
)
from outlook_mcp.outlook import OutlookClient  # noqa: E402
from outlook_mcp.scheduling import find_common_slots, parse_workdays  # noqa: E402
from outlook_mcp.server import build_server  # noqa: E402
from outlook_mcp.teams_ui import extract_link  # noqa: E402

# 2030-01-06 is a Sunday, so 06..10 are Sun-Thu and 11 is a Friday.
SUNDAY = date(2030, 1, 6)
LONG_BEFORE = datetime(2000, 1, 1)


def slots(busy, duration=30, **kw):
    return find_common_slots(
        busy,
        SUNDAY,
        kw.pop("earliest", datetime(2030, 1, 6, 0, 0)),
        kw.pop("latest", datetime(2030, 1, 6, 23, 59)),
        duration,
        time(9, 0),
        time(12, 0),
        kw.pop("workdays", parse_workdays("sun,mon,tue,wed,thu")),
        now=LONG_BEFORE,
        **kw,
    )


def day_status(busy_ranges, total=48 * 7):
    """Half-hour status string; busy_ranges are (first_slot, last_slot, char)."""
    chars = ["0"] * total
    for first, last, char in busy_ranges:
        for i in range(first, last + 1):
            chars[i] = char
    return "".join(chars)


def test_slots_require_everyone_free():
    # 09:00-10:00 busy for A (slots 18,19); 10:00-10:30 busy for B (slot 20).
    result = slots({"A": day_status([(18, 19, "2")]), "B": day_status([(20, 20, "2")])})
    assert result[0]["start"] == "2030-01-06T10:30"


def test_tentative_blocks_unless_allowed():
    status = {"A": day_status([(18, 21, "1")])}
    assert slots(status, limit=1)[0]["start"] == "2030-01-06T11:00"
    assert slots(status, limit=1, allow_tentative=True)[0]["start"] == "2030-01-06T09:00"


def test_slot_must_fit_whole_duration_inside_working_hours():
    result = slots({"A": day_status([])}, duration=90, limit=50)
    assert result[-1]["start"] == "2030-01-06T10:30"
    assert result[-1]["end"] == "2030-01-06T12:00"


def test_weekend_days_are_skipped():
    friday = date(2030, 1, 11)
    result = find_common_slots(
        {"A": day_status([], 48 * 14)},
        SUNDAY,
        datetime.combine(friday, time.min),
        datetime.combine(friday, time(23, 59)),
        30,
        time(9, 0),
        time(12, 0),
        parse_workdays("sun,mon,tue,wed,thu"),
        now=LONG_BEFORE,
    )
    assert result == []


def test_time_past_the_known_free_busy_data_is_not_offered():
    short = "0" * 20  # data ends at 10:00
    result = slots({"A": short}, limit=50)
    assert [s["start"] for s in result][-1] == "2030-01-06T09:30"


class FakeRecipient:
    def __init__(self, name, status="", resolves=True):
        self.Name = name
        self._status = status
        self._resolves = resolves
        self.Type = 1
        self.Resolved = resolves

    def Resolve(self):
        return self._resolves

    def FreeBusy(self, start, minutes, complete):
        return self._status


class FakeRecipients:
    def __init__(self):
        self.items = []

    def Add(self, address):
        recipient = FakeRecipient(address)
        self.items.append(recipient)
        return recipient

    def ResolveAll(self):
        return all(r.Resolved for r in self.items)

    @property
    def Count(self):
        return len(self.items)

    def Item(self, index):
        return self.items[index - 1]


class FakeMeeting:
    def __init__(self):
        self.Recipients = FakeRecipients()
        self.Body = ""
        self.calls = []

    def Save(self):
        self.calls.append("save")

    def Send(self):
        self.calls.append("send")

    def Close(self, mode):
        self.calls.append(f"close{mode}")


class FakeNamespace:
    def __init__(self, directory):
        self.CurrentUser = FakeRecipient("Me", day_status([]))
        self._directory = directory

    def CreateRecipient(self, name):
        return self._directory.get(name, FakeRecipient(name, resolves=False))


class FakeApp:
    def __init__(self, namespace):
        self._namespace = namespace
        self.meeting = FakeMeeting()

    def GetNamespace(self, _):
        return self._namespace

    def CreateItem(self, kind):
        assert kind == 1
        return self.meeting


def make_client(directory=None, teams=None, allow_write=False):
    app = FakeApp(FakeNamespace(directory or {}))
    config = OutlookConfig(allow_write=allow_write)
    kwargs = {"teams_inserter": teams} if teams else {}
    return OutlookClient(config, app=app, **kwargs), config, app


def test_find_free_slots_reports_unresolved_and_no_data():
    directory = {
        "Dana": FakeRecipient("Dana Levi", day_status([(18, 19, "2")])),
        "Ghost": FakeRecipient("Ghost", ""),
    }
    client, _, _ = make_client(directory)
    result = client.find_free_slots(
        "Dana; Ghost; Nobody", "2030-01-06 09:00", "2030-01-06 12:00", limit=1
    )
    assert result["slots"][0]["start"] == "2030-01-06T10:00"
    assert result["checked"] == ["me", "Dana Levi"]
    assert result["no_data"] == ["Ghost"]
    assert result["unresolved"] == ["Nobody"]


def test_find_free_slots_fails_loudly_without_any_data():
    client, _, _ = make_client({})
    with pytest.raises(OutlookUnavailableError):
        client.find_free_slots(
            "Nobody", "2030-01-06", "2030-01-07", include_me=False
        )


def test_create_meeting_is_saved_unsent_with_teams_link_by_default():
    client, _, app = make_client(teams=lambda item: "https://teams.microsoft.com/meet/1")
    result = client.create_meeting(
        "a@nuvoton.com", "Sync", "2030-01-06 10:00", optional_attendees="b@nuvoton.com"
    )
    assert result["sent"] is False
    assert result["teams_link"] == "https://teams.microsoft.com/meet/1"
    assert app.meeting.calls == ["save", "close0"]
    assert [r.Type for r in app.meeting.Recipients.items] == [1, 2]


def test_create_meeting_discards_the_item_if_teams_fails():
    def broken(item):
        raise OutlookUnavailableError("no button")

    client, _, app = make_client(teams=broken)
    with pytest.raises(OutlookUnavailableError):
        client.create_meeting("a@nuvoton.com", "Sync", "2030-01-06 10:00")
    assert app.meeting.calls == ["close1"]


def test_create_meeting_rejects_unresolved_attendee_without_saving():
    client, _, app = make_client(teams=lambda item: "")
    app.meeting.Recipients.Add = lambda address: _unresolved(app.meeting, address)
    with pytest.raises(ValueError, match="resolve"):
        client.create_meeting("who@x", "Sync", "2030-01-06 10:00", teams=False)
    assert "save" not in app.meeting.calls


def _unresolved(meeting, address):
    recipient = FakeRecipient(address, resolves=False)
    meeting.Recipients.items.append(recipient)
    return recipient


def test_sending_a_meeting_requires_write_access():
    client, config, app = make_client(teams=lambda item: "")
    create = server_tool(client, config, "create_meeting")
    with pytest.raises(OutlookWriteDisabledError):
        create(attendees="a@nuvoton.com", subject="Sync", start="2030-01-06 10:00", send=True)
    assert app.meeting.calls == []


def test_unsent_meeting_needs_no_write_access():
    client, config, app = make_client(teams=lambda item: "")
    create = server_tool(client, config, "create_meeting")
    result = create(attendees="a@nuvoton.com", subject="Sync", start="2030-01-06 10:00")
    assert result["sent"] is False


def server_tool(client, config, name):
    server = build_server(config, client)
    return server._tool_manager.get_tool(name).fn


def test_extract_link_finds_teams_join_url():
    text = "Join: https://teams.microsoft.com/meet/49?p=abc <https://x>\nMeeting ID"
    assert extract_link(text) == "https://teams.microsoft.com/meet/49?p=abc"
    assert extract_link("no link here") == ""
