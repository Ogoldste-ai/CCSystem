"""Configuration for the TEB MCP server, read from the environment.

Nothing here is secret, but the CE machine addresses are internal
infrastructure, so they stay in per-user client configuration rather than in
committed files - the same handling the other servers in this repo use for
credentials.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

# Veloce chip-emulation machines, from BMC\Common\host\ce_veloce.h in the
# ec_accurev_git work repo. These are aliases only: TEB_HOST accepts a literal
# IP too, because the addresses are expected to change.
CE_MACHINES = {
    "cm1": "134.86.33.137",
    "cm2": "134.86.33.138",
    "cm3": "134.86.33.130",
    "cm4": "134.86.33.131",
    "cm5": "134.86.33.141",
    "cm6": "134.86.33.142",
}

MODES = ("virtual", "usb-local", "usb-remote")

BOARDS = ("any", "virtual", "teb3", "teb4", "ceb1")


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _path(name: str) -> str:
    """Read a path setting, expanding %VARS% and ~.

    MCP client configs commonly embed ``%LOCALAPPDATA%`` and not every client
    expands it before handing the environment to the server, so do it here.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return ""
    return os.path.expanduser(os.path.expandvars(raw))


def _int_or_none(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        return None


def resolve_host(host: str) -> str:
    """Map a ``cm1``..``cm6`` alias to an IP; pass anything else through."""
    if not host:
        return host
    return CE_MACHINES.get(host.strip().lower(), host.strip())


def find_python32() -> str | None:
    """Locate a 32-bit Python capable of loading TEB_If.dll.

    ``TEB_PYTHON32`` wins. Otherwise try the conventional install locations,
    including the embeddable distribution this skill's README recommends.
    """
    explicit = _path("TEB_PYTHON32")
    if explicit:
        return explicit

    candidates = [
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "teb-mcp", "python32", "python.exe"
        ),
        r"C:\Python312-32\python.exe",
        r"C:\Python311-32\python.exe",
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Programs",
            "Python",
            "Python312-32",
            "python.exe",
        ),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    return shutil.which("python32")


@dataclass
class TebConfig:
    mode: str = "virtual"
    host: str = ""
    port: int | None = None
    board: str = ""
    instance: int = 0
    bitstream_dir: str = ""
    dll_path: str = ""
    python32: str | None = None
    worker_log: str = ""
    call_timeout: float = 60.0
    connect_timeout: float = 300.0
    allow_write: bool = False
    allow_power: bool = False
    max_voltage: float | None = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "TebConfig":
        warnings: list[str] = []

        mode = (os.environ.get("TEB_MODE") or "virtual").strip().lower()
        if mode not in MODES:
            warnings.append(
                "TEB_MODE=%r is not one of %s; falling back to 'virtual'"
                % (mode, ", ".join(MODES))
            )
            mode = "virtual"

        board = (os.environ.get("TEB_BOARD") or "").strip().lower()
        if board and board not in BOARDS:
            warnings.append(
                "TEB_BOARD=%r is not one of %s; ignoring"
                % (board, ", ".join(BOARDS))
            )
            board = ""

        python32 = find_python32()
        if not python32:
            warnings.append(
                "no 32-bit Python found - set TEB_PYTHON32. The TEB DLL is "
                "32-bit and cannot be loaded by this interpreter."
            )

        port = _int_or_none("TEB_PORT")
        if port is None and mode in ("virtual", "usb-remote"):
            warnings.append(
                "TEB_PORT is not set; %s mode needs a port, which is chosen "
                "per run rather than having a default" % mode
            )

        return cls(
            mode=mode,
            host=resolve_host(os.environ.get("TEB_HOST", "")),
            port=port,
            board=board,
            instance=_int_or_none("TEB_INSTANCE") or 0,
            bitstream_dir=_path("TEB_BITSTREAM_DIR"),
            dll_path=_path("TEB_DLL_PATH"),
            python32=python32,
            worker_log=_path("TEB_WORKER_LOG"),
            call_timeout=float(os.environ.get("TEB_CALL_TIMEOUT", "60") or 60),
            connect_timeout=float(os.environ.get("TEB_CONNECT_TIMEOUT", "300") or 300),
            allow_write=_flag("TEB_ALLOW_WRITE"),
            allow_power=_flag("TEB_ALLOW_POWER"),
            max_voltage=(
                float(os.environ["TEB_MAX_VOLTAGE"])
                if os.environ.get("TEB_MAX_VOLTAGE", "").strip()
                else None
            ),
            warnings=warnings,
        )

    def describe(self) -> dict:
        return {
            "mode": self.mode,
            "host": self.host or None,
            "port": self.port,
            "board": self.board or None,
            "instance": self.instance,
            "bitstream_dir": self.bitstream_dir or None,
            "python32": self.python32,
            "write_enabled": self.allow_write,
            "power_enabled": self.allow_power,
            "max_voltage": self.max_voltage,
            "warnings": list(self.warnings),
        }
