"""Symbolic TEB pin names parsed from ``TebConnector.h``.

Letting the agent say ``GPIO_101`` instead of ``101`` removes a whole class of
mistakes, and the connector/pin comments in the header are exactly the context
needed to reason about what is physically wired where.

The header is part of the Nuvoton SDK install rather than this repository, so
parsing is best-effort: if the SDK is missing, the map is simply empty and the
numeric pin arguments still work.
"""

from __future__ import annotations

import os
import re

DEFAULT_HEADER = r"C:\Program Files\Nuvoton\TEB_Interface\Include\TebConnector.h"

# e.g. "#define _TEB_GPIO_101     101 // GPIO_101  Connector-1 Pin-01"
_DEFINE = re.compile(
    r"^#define\s+_TEB_(?P<name>\w+)\s+(?P<value>\d+)\s*(?://\s*(?P<comment>.*))?$"
)
_LOCATION = re.compile(r"Connector-(?P<connector>\d+)\s+Pin-(?P<pin>\d+)")


def header_path() -> str:
    return os.environ.get("TEB_CONNECTOR_HEADER", "").strip() or DEFAULT_HEADER


def load_pins(path: str | None = None) -> dict:
    """Parse the connector header into a structured pin map."""
    path = path or header_path()
    if not os.path.exists(path):
        return {"available": False, "source": path, "pins": {}, "count": 0}

    pins: dict[str, dict] = {}
    with open(path, "r", encoding="latin-1") as fh:
        for line in fh:
            match = _DEFINE.match(line.strip())
            if not match:
                continue

            name = match.group("name")
            entry = {"name": name, "value": int(match.group("value"))}

            comment = (match.group("comment") or "").strip()
            if comment:
                location = _LOCATION.search(comment)
                if location:
                    entry["connector"] = int(location.group("connector"))
                    entry["pin"] = int(location.group("pin"))
                note = _LOCATION.sub("", comment).replace(name, "", 1).strip()
                if note:
                    entry["note"] = note

            entry["group"] = _group_of(name)
            pins[name] = entry

    return {
        "available": True,
        "source": path,
        "count": len(pins),
        "pins": pins,
    }


def _group_of(name: str) -> str:
    for prefix in ("GPIO_", "ADC", "DA", "PLL_", "PS_"):
        if name.startswith(prefix):
            return prefix.rstrip("_")
    return "other"


class PinMap:
    """Lazily-loaded pin map with name/number resolution."""

    def __init__(self, path: str | None = None):
        self._path = path
        self._data: dict | None = None

    @property
    def data(self) -> dict:
        if self._data is None:
            self._data = load_pins(self._path)
        return self._data

    def resolve(self, pin) -> int:
        """Accept 101, "101", "GPIO_101" or "_TEB_GPIO_101" and return 101."""
        if isinstance(pin, int):
            return pin

        text = str(pin).strip()
        if not text:
            raise ValueError("pin is required")

        try:
            return int(text, 0)
        except ValueError:
            pass

        key = text[len("_TEB_"):] if text.startswith("_TEB_") else text
        pins = self.data.get("pins") or {}

        for candidate in (key, key.upper()):
            if candidate in pins:
                return pins[candidate]["value"]

        # The header writes GPIO_B06; the netlist - and therefore ``pin_net``
        # and ``list_pins`` - writes GPIO_B6. Accepting only one spelling means
        # a name this server just handed out is rejected by the tool it was
        # meant for.
        match = re.fullmatch(r"(GPIO_[A-Za-z])0*(\d+)", key)
        if match:
            family, index = match.group(1).upper(), int(match.group(2))
            for candidate in ("%s%02d" % (family, index), "%s%d" % (family, index)):
                if candidate in pins:
                    return pins[candidate]["value"]

        if not self.data.get("available"):
            raise ValueError(
                "cannot resolve pin name %r because TebConnector.h was not "
                "found at %s - pass a numeric pin instead"
                % (text, self.data.get("source"))
            )
        raise ValueError("unknown pin name %r" % text)
