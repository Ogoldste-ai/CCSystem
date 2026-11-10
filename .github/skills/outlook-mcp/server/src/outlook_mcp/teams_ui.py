"""Add a Teams meeting link to an open Outlook meeting window.

The Teams add-in has no COM surface and its ribbon button is not a built-in
Office command (``ExecuteMso`` cannot reach it, ``COMAddIn.Object`` is None),
so the only route is to click that button through Windows UI Automation, the
same as a user would. This depends on the English "Teams Meeting" button label
and on the item being displayed in an Inspector window.
"""

from __future__ import annotations

import re
import time
from typing import Any

from .config import OutlookUnavailableError

# Imported at module load on purpose: pywinauto changes COM threading settings
# when it loads, and importing it after Outlook COM objects exist breaks them
# ("CreateItem.Display" AttributeError).
try:
    from pywinauto import Desktop
except ImportError:  # pragma: no cover - Windows only
    Desktop = None

BUTTON_NAME = "Teams Meeting"
LINK_PATTERN = re.compile(r"https://teams\.(?:microsoft|live)\.com/[^\s<>]+")


def extract_link(text: str) -> str:
    match = LINK_PATTERN.search(text or "")
    return match.group(0) if match else ""


def insert_teams_link(item: Any, timeout: float = 30.0) -> str:
    """Click the Teams Meeting button for ``item`` and return the join link.

    The item is displayed here; the caller owns saving, sending and closing it.
    """
    if Desktop is None:  # pragma: no cover - Windows only
        raise OutlookUnavailableError(
            "pywinauto is not installed, so the Teams link cannot be added. "
            "Install it with 'pip install pywinauto'."
        )

    item.Display()
    caption = str(item.GetInspector.Caption or "").strip()

    deadline = time.monotonic() + timeout
    button = None
    while time.monotonic() < deadline and button is None:
        for window in Desktop(backend="uia").windows():
            if (window.window_text() or "").strip() != caption:
                continue
            for control in window.descendants(control_type="Button"):
                if control.window_text() == BUTTON_NAME:
                    button = control
                    break
            if button is not None:
                break
        if button is None:
            time.sleep(0.5)
    if button is None:
        raise OutlookUnavailableError(
            f"Could not find the '{BUTTON_NAME}' button in the Outlook window "
            f"'{caption}'. The Teams add-in must be enabled and Outlook's UI "
            "language must be English."
        )

    button.invoke()
    while time.monotonic() < deadline:
        link = extract_link(str(item.Body or ""))
        if link:
            return link
        time.sleep(0.5)
    raise OutlookUnavailableError(
        "Clicked 'Teams Meeting' but no join link appeared in the invite body."
    )
