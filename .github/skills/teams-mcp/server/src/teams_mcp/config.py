from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

TRUTHY = {"1", "true", "yes", "on"}

FILEDROP = "filedrop"
GRAPH = "graph"
BACKENDS = (FILEDROP, GRAPH)

WRITE_DISABLED_MESSAGE = (
    "Teams write operations are disabled. Set TEAMS_ALLOW_WRITE=1 in the MCP server "
    "environment and reload the client to enable them. This guard exists because a "
    "reply is posted under your own Microsoft Teams identity and cannot be unsent."
)


class TeamsWriteDisabledError(RuntimeError):
    """A write tool was called while TEAMS_ALLOW_WRITE was not enabled."""


class TeamsConfigError(RuntimeError):
    """The server is not configured well enough to serve this request."""


def _path_from_env(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip().strip('"')
    return Path(os.path.expandvars(raw)).expanduser() if raw else None


def _default_state_file() -> Path:
    root = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(root) if root else Path.home()
    return base / "teams-mcp" / "seen-messages.json"


@dataclass(slots=True)
class TeamsConfig:
    """Runtime configuration, read from the environment.

    Deliberately never raises on construction. A half-configured server still
    starts so that ``health()`` can explain what is missing, which is far easier
    to diagnose than an MCP client reporting that the process died at spawn.
    """

    backend: str = FILEDROP
    inbox_dir: Path | None = None
    outbox_dir: Path | None = None
    archive_dir: Path | None = None
    state_file: Path = field(default_factory=_default_state_file)
    client_id: str = ""
    tenant_id: str = ""
    webhook_url: str = ""
    user_agent: str = "teams-mcp/0.1"
    timeout_seconds: float = 30.0
    allow_write: bool = False

    @classmethod
    def from_env(cls) -> "TeamsConfig":
        backend = os.environ.get("TEAMS_BACKEND", FILEDROP).strip().lower() or FILEDROP
        inbox = _path_from_env("TEAMS_INBOX_DIR")
        outbox = _path_from_env("TEAMS_OUTBOX_DIR")
        archive = _path_from_env("TEAMS_ARCHIVE_DIR")
        if archive is None and outbox is not None:
            archive = outbox / "sent"
        state = _path_from_env("TEAMS_STATE_FILE") or _default_state_file()
        return cls(
            backend=backend,
            inbox_dir=inbox,
            outbox_dir=outbox,
            archive_dir=archive,
            state_file=state,
            client_id=os.environ.get("TEAMS_CLIENT_ID", "").strip(),
            tenant_id=os.environ.get("TEAMS_TENANT_ID", "").strip(),
            webhook_url=os.environ.get("TEAMS_WEBHOOK_URL", "").strip(),
            allow_write=os.environ.get("TEAMS_ALLOW_WRITE", "").strip().lower() in TRUTHY,
        )

    @property
    def has_webhook(self) -> bool:
        return bool(self.webhook_url)

    def problems(self) -> list[str]:
        """Configuration errors, in the order a user should fix them."""
        issues: list[str] = []
        if self.backend not in BACKENDS:
            issues.append(
                f"TEAMS_BACKEND is {self.backend!r}; expected one of {', '.join(BACKENDS)}."
            )
            return issues
        if self.backend == FILEDROP:
            if self.inbox_dir is None:
                issues.append("TEAMS_INBOX_DIR is not set; the filedrop backend reads messages from it.")
            elif not self.inbox_dir.is_dir():
                issues.append(f"TEAMS_INBOX_DIR does not exist: {self.inbox_dir}")
            if self.allow_write and self.outbox_dir is None and not self.has_webhook:
                issues.append(
                    "TEAMS_ALLOW_WRITE is enabled but neither TEAMS_OUTBOX_DIR nor "
                    "TEAMS_WEBHOOK_URL is set, so replies have nowhere to go."
                )
        else:
            if not self.client_id:
                issues.append(
                    "TEAMS_CLIENT_ID is not set. Register a single-tenant public-client app "
                    "with delegated Chat.Read and use its application (client) id."
                )
            if not self.tenant_id:
                issues.append("TEAMS_TENANT_ID is not set.")
        return issues

    def require_write(self) -> None:
        if not self.allow_write:
            raise TeamsWriteDisabledError(WRITE_DISABLED_MESSAGE)

    def require_ready(self) -> None:
        issues = self.problems()
        if issues:
            raise TeamsConfigError(" ".join(issues))
