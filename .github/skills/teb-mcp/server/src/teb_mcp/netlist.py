"""Board connectivity for the TEB, parsed from a Cadence Allegro netlist.

``pinmap.py`` answers "what is this pin called"; this module answers "what is
it actually wired to". Together they turn ``GPIO_A5`` into "net ``GPIO_A5`` on
connector ``J7`` pin 5, also reaching ``U60.AH33``", which is the difference
between driving a pin and knowing what you just drove.

The netlist ships with the skill under ``data/`` because it is board topology,
not a secret, and because the alternative - pointing at a file in someone's
Downloads folder - silently rots. Parsing is deliberately best-effort in the
same way ``pinmap.py`` is: a missing or unreadable netlist yields an empty map
and every numeric/symbolic pin operation keeps working.

Format notes (Allegro 23.1 "Telesis"):

* Sections are introduced by a line starting with ``$``. The file uses each
  marker twice - once for the data itself and once, later, paired with
  ``$A_PROPERTIES`` for per-object properties - so only the *first* occurrence
  of ``$NETS`` is the net list, and it ends at the next section marker.
* A record is ``NAME ; REFDES.PIN REFDES.PIN ...``.
* A trailing ``,`` continues the record onto the following indented line.
* Any token may be single-quoted when it contains characters Allegro treats as
  special (``'MAX15020ATP+'``), so quotes are stripped, not trusted.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))

# ``src/teb_mcp/netlist.py`` -> ``<skill>/data``
DEFAULT_NETLIST = os.path.abspath(
    os.path.join(_HERE, "..", "..", "..", "data", "TEB3_Rev_C_netlist_290926.txt")
)

# Maps a *net-name* family to the connector it lands on. This is read out of
# $NETS and is solid: the net named GPIO_B6 really does touch J8 pin 6.
#
# It does NOT mean that the TebConnector.h symbol GPIO_B06 is that pin. The
# board names each net after the connector pin it reaches, so matching the two
# on name is circular - see ``CONNECTOR_EVIDENCE["symbol_join_warning"]``.
# Prefer connector-location lookups (``pin="J8.6"``) when it matters.
CONNECTOR_REFDES = {
    "GPIO_A": "J7",
    "GPIO_B": "J8",
    "GPIO_C": "J12",
    "GPIO_D": "J14",
    "GPIO_E": "J24",
    "GPIO_G": "J21",
    "ADC": "J22",
    "DA": "J22",
}

# Which "TEB I/F <n>" heading in TebConnector.h each family sits under.
CONNECTOR_INTERFACE = {
    "GPIO_A": 10,
    "GPIO_B": 11,
    "GPIO_C": 12,
    "GPIO_D": 13,
    "GPIO_E": 14,
    "GPIO_F": 15,
}

CONNECTOR_EVIDENCE = {
    "status": "PARTIALLY REFUTED - see symbol_join_warning",
    "net_to_connector": (
        "SOLID. This is read straight out of $NETS: the net named GPIO_B6 "
        "touches J8 pin 6. Lookups by connector location (pin='J8.6') and by "
        "net name are trustworthy."
    ),
    "symbol_join_warning": (
        "NOT ESTABLISHED. Joining a TebConnector.h symbol (GPIO_B06, value "
        "1106) to the net named GPIO_B6 was done on name equality alone, and "
        "the '239/239 index matches' originally recorded here proved nothing: "
        "the board names each net after the connector pin it lands on, so the "
        "index necessarily matched. It was a circular check.\n"
        "Evidence against the join: the work repo drives _TEB_GPIO_B01, B03, "
        "B05 .. B17 (EC/Common/Boards/SVB/SVB_Akko.cpp), but J8's odd pins "
        "carry POWER_OUT0-7 and ID0-6, not GPIO - so those symbols cannot be "
        "odd J8 pins. The header's letter families and the board's net-name "
        "letters are most likely two unrelated numbering schemes that happen "
        "to share a prefix."
    ),
    "interfaces_1_to_8_are_real": (
        "An earlier version of this file claimed GPIO_101..GPIO_950 were 'not "
        "on the TEB3 board'. That is WRONG. EC/Common/Boards/SVB/SVB_Ramon.cpp "
        "maps 286 pins across TEB I/F 1-8 and runs on this board "
        "(board_generation=3, composition Ramon/1.2). Those interfaces are "
        "real, in use, and their connector is simply not yet identified."
    ),
    "verified_on": "TEB3_Rev_C_netlist_290926.txt (TEB3_Revc_upadated.brd)",
    "how_to_settle_it": (
        "Drive one candidate symbol at a time and measure the connector pin, "
        "or obtain the TEB3 schematic sheet that labels each QSS-025 header "
        "with its TEB I/F number. Until then, prefer connector-location "
        "lookups (pin='J8.6') over symbol lookups."
    ),
}

_FAMILY = re.compile(r"^(?P<family>GPIO_[A-Z]|ADC|DA)(?P<index>\d+)$")


def netlist_path() -> str:
    return os.environ.get("TEB_NETLIST", "").strip() or DEFAULT_NETLIST


def _unquote(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == "'" and token[-1] == "'":
        return token[1:-1]
    return token


def iter_records(lines) -> "list[str]":
    """Join Allegro continuation lines into one logical record each."""
    records: list[str] = []
    buffer = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith(","):
            buffer += " " + stripped[:-1].strip()
            continue
        buffer += " " + stripped
        records.append(buffer.strip())
        buffer = ""
    if buffer.strip():
        records.append(buffer.strip())
    return records


def _section(lines: "list[str]", marker: str) -> "list[str]":
    """Return the lines of the first ``marker`` section.

    Only the first occurrence counts: Allegro repeats every marker later on,
    paired with ``$A_PROPERTIES``, for per-object properties.
    """
    try:
        start = next(
            i for i, line in enumerate(lines) if line.strip() == marker
        )
    except StopIteration:
        return []
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("$"):
            return lines[start + 1 : i]
    return lines[start + 1 :]


def load_netlist(path: str | None = None) -> dict:
    """Parse the netlist into nets, per-refdes pins and a connector view."""
    path = path or netlist_path()
    if not os.path.exists(path):
        return {
            "available": False,
            "source": path,
            "nets": {},
            "refdes": {},
            "devices": {},
            "connectors": {},
            "count": 0,
        }

    with open(path, "r", encoding="latin-1") as handle:
        lines = handle.read().splitlines()

    nets: dict[str, list[str]] = {}
    refdes: dict[str, dict[str, str]] = defaultdict(dict)

    for record in iter_records(_section(lines, "$NETS")):
        name, separator, rest = record.partition(";")
        if not separator:
            continue
        name = _unquote(name)
        if not name:
            continue
        pins = [_unquote(token) for token in rest.split() if token.strip()]
        nets[name] = pins
        for pin in pins:
            part, dot, number = pin.rpartition(".")
            if dot and part:
                refdes[part][number] = name

    return {
        "available": True,
        "source": path,
        "count": len(nets),
        "nets": nets,
        "refdes": dict(refdes),
        "devices": _parse_packages(lines),
        "connectors": _connector_view(nets),
    }


def _parse_packages(lines: "list[str]") -> dict:
    """Map each refdes to its device name, from ``$PACKAGES``.

    Saying "J7 is a QSS-025-01-F-D-A" costs nothing here and turns a bare
    refdes in a lookup into something recognisable on the bench.
    """
    devices: dict[str, str] = {}
    for record in iter_records(_section(lines, "$PACKAGES")):
        head, separator, rest = record.partition(";")
        if not separator:
            continue
        fields = [_unquote(f) for f in head.split("!")]
        device = fields[2] if len(fields) > 2 else (fields[0] if fields else "")
        for token in rest.split():
            token = _unquote(token)
            if token:
                devices[token] = device
    return devices


def _connector_view(nets: dict) -> dict:
    """Index nets by the symbolic names used in ``TebConnector.h``.

    Keys are the *header* spelling (zero padded, e.g. ``GPIO_A05``) as well as
    the netlist spelling, so a lookup succeeds whichever the caller has.
    """
    view: dict[str, dict] = {}

    for name, pins in nets.items():
        match = _FAMILY.match(name)
        analog = None
        if not match:
            analog = re.fullmatch(r"ANALOG_(INPUTS|OUTPUTS)(\d+)", name)
            if not analog:
                continue
            family = "ADC" if analog.group(1) == "INPUTS" else "DA"
            index = int(analog.group(2))
        else:
            family = match.group("family")
            index = int(match.group("index"))

        expected = CONNECTOR_REFDES.get(family)
        location = None
        for pin in pins:
            part, dot, number = pin.rpartition(".")
            if dot and part == expected:
                location = {"refdes": part, "pin": number}
                break

        entry = {
            "net": name,
            "family": family,
            "index": index,
            "interface": CONNECTOR_INTERFACE.get(family),
            "connector": location,
            "endpoints": [p for p in pins if not (location and p ==
                          "%s.%s" % (location["refdes"], location["pin"]))],
        }

        view[name] = entry
        if family.startswith("GPIO_"):
            view["%s%02d" % (family, index)] = entry
        else:
            view["%s%d" % (family, index)] = entry

    return view


class BoardNets:
    """Lazily-loaded netlist with symbol-name lookup."""

    def __init__(self, path: str | None = None):
        self._path = path
        self._data: dict | None = None

    @property
    def data(self) -> dict:
        if self._data is None:
            self._data = load_netlist(self._path)
        return self._data

    @property
    def available(self) -> bool:
        return bool(self.data.get("available"))

    def for_symbol(self, name: str) -> dict | None:
        """Look up a ``TebConnector.h`` symbol, e.g. ``GPIO_A5`` or ``ADC7``."""
        text = str(name or "").strip()
        if not text:
            return None
        if text.startswith("_TEB_"):
            text = text[len("_TEB_") :]

        view = self.data.get("connectors") or {}
        if text in view:
            return view[text]

        # Tolerate either spelling of the index: GPIO_A5 and GPIO_A05.
        match = _FAMILY.match(text.upper())
        if match:
            family, index = match.group("family"), int(match.group("index"))
            for candidate in ("%s%02d" % (family, index), "%s%d" % (family, index)):
                if candidate in view:
                    return view[candidate]
        return None

    def for_pin(self, refdes: str, pin) -> str | None:
        """Return the net on ``refdes`` pin ``pin``, e.g. ``("J7", 5)``."""
        table = (self.data.get("refdes") or {}).get(str(refdes).strip().upper())
        if not table:
            return None
        return table.get(str(pin).strip())

    def net(self, name: str) -> dict | None:
        """Return a net and everything it connects."""
        pins = (self.data.get("nets") or {}).get(str(name or "").strip())
        if pins is None:
            return None
        return {"net": name, "pin_count": len(pins), "pins": pins}

    def device(self, refdes: str) -> str | None:
        """Return the part name for a refdes, e.g. ``J7`` -> ``QSS-025-...``."""
        return (self.data.get("devices") or {}).get(
            str(refdes or "").strip().upper()
        )
