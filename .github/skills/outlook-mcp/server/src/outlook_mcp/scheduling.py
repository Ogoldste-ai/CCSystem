"""Pure scheduling logic: parsing and common-free-slot search.

Kept free of COM so it can be tested without Outlook. Input is the per-person
free/busy strings Outlook returns from ``Recipient.FreeBusy(day, 30, True)``:
one character per 30 minutes starting at midnight of ``anchor`` where
0=free, 1=tentative, 2=busy, 3=out of office, 4=working elsewhere.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

SLOT_MINUTES = 30

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# Israeli work week by default; Fri/Sat are the weekend.
DEFAULT_WORKDAYS = "sun,mon,tue,wed,thu"


def parse_when(text: str) -> datetime:
    """Parse 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' (ISO 'T' form also accepted)."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("A date/time is required (YYYY-MM-DD or YYYY-MM-DD HH:MM).")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            f"Could not parse {text!r}; use YYYY-MM-DD or YYYY-MM-DD HH:MM."
        ) from exc
    return parsed.replace(tzinfo=None)


def parse_clock(text: str) -> time:
    raw = (text or "").strip()
    try:
        hours, minutes = raw.split(":")
        return time(int(hours), int(minutes))
    except ValueError as exc:
        raise ValueError(f"Could not parse time {text!r}; use HH:MM.") from exc


def parse_workdays(text: str) -> set[int]:
    days: set[int] = set()
    for part in (text or "").replace(";", ",").split(","):
        key = part.strip().lower()[:3]
        if not key:
            continue
        if key not in WEEKDAYS:
            raise ValueError(f"Unknown weekday {part!r}; use names like 'sun,mon,tue'.")
        days.add(WEEKDAYS[key])
    if not days:
        raise ValueError("workdays must name at least one weekday.")
    return days


def _round_up_to_slot(moment: datetime) -> datetime:
    floor = moment.replace(minute=0, second=0, microsecond=0)
    elapsed = (moment - floor).total_seconds() / 60
    steps = -(-elapsed // SLOT_MINUTES)
    return floor + timedelta(minutes=steps * SLOT_MINUTES)


def find_common_slots(
    busy: dict[str, str],
    anchor: date,
    earliest: datetime,
    latest: datetime,
    duration_minutes: int,
    work_start: time,
    work_end: time,
    workdays: set[int],
    now: datetime,
    limit: int = 10,
    allow_tentative: bool = False,
) -> list[dict[str, Any]]:
    """Earliest-first slots where every person with data is free.

    A slot is only offered when every covered half-hour is known and free for
    everyone; a time beyond the end of someone's free/busy string is unknown
    and therefore not offered. ``busy`` should already exclude people without
    any data.
    """
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive.")
    duration = timedelta(minutes=duration_minutes)
    needed = -(-duration_minutes // SLOT_MINUTES)
    base = datetime.combine(anchor, time.min)
    blocking = set("23") if allow_tentative else set("123")
    floor = max(earliest, now)

    def fits(start: datetime) -> bool:
        index = int((start - base).total_seconds() // 60) // SLOT_MINUTES
        if index < 0:
            return False
        for status in busy.values():
            window = status[index : index + needed]
            if len(window) < needed or blocking & set(window):
                return False
        return True

    slots: list[dict[str, Any]] = []
    day = earliest.date()
    while day <= latest.date() and len(slots) < limit:
        if day.weekday() in workdays:
            cursor = _round_up_to_slot(datetime.combine(day, work_start))
            day_end = datetime.combine(day, work_end)
            while cursor + duration <= day_end and len(slots) < limit:
                if cursor >= floor and cursor + duration <= latest and fits(cursor):
                    slots.append(
                        {
                            "start": cursor.isoformat(timespec="minutes"),
                            "end": (cursor + duration).isoformat(timespec="minutes"),
                        }
                    )
                cursor += timedelta(minutes=SLOT_MINUTES)
        day += timedelta(days=1)
    return slots
