from __future__ import annotations

import os
from dataclasses import dataclass

TRUTHY = {"1", "true", "yes", "on"}

WRITE_DISABLED_MESSAGE = (
    "Outlook write operations are disabled. Set OUTLOOK_ALLOW_WRITE=1 in the MCP server "
    "environment and reload the client to enable them. This guard exists because mail sent "
    "through Outlook goes out under your own address, is indistinguishable from mail you "
    "typed, and cannot be unsent."
)


class OutlookWriteDisabledError(RuntimeError):
    """A write tool was called while OUTLOOK_ALLOW_WRITE was not enabled."""


class OutlookUnavailableError(RuntimeError):
    """Outlook could not be reached over COM."""


def _int_from_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def default_attachment_dir() -> str:
    """Where attachments land when the caller names no destination.

    Deliberately outside the mailbox and outside any repo: attachments are
    untrusted files that arrived by mail, and they should never be written
    somewhere a build or a commit might pick them up by accident.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "outlook-mcp", "attachments")


@dataclass(slots=True)
class OutlookConfig:
    """Runtime configuration, read from the environment.

    Like the other servers here, this never raises on construction: a
    half-configured server still starts so ``health()`` can explain what is
    wrong, which beats an MCP client reporting that the process died at spawn.
    """

    preview_chars: int = 400
    max_results: int = 50
    max_body_chars: int = 20000
    list_recipients: int = 3
    store_name: str = ""
    allow_write: bool = False
    allow_send: bool = True
    attachment_dir: str = ""
    max_attachment_mb: int = 20

    @classmethod
    def from_env(cls) -> "OutlookConfig":
        return cls(
            preview_chars=_int_from_env("OUTLOOK_PREVIEW_CHARS", 400, 0, 20000),
            max_results=_int_from_env("OUTLOOK_MAX_RESULTS", 50, 1, 500),
            # A single GitHub notification mail measured 310,000 characters, of
            # which ~10 lines were written by the sender. 0 disables the cap.
            max_body_chars=_int_from_env("OUTLOOK_MAX_BODY_CHARS", 20000, 0, 2000000),
            # Applies to list results only; one message always shows everyone.
            list_recipients=_int_from_env("OUTLOOK_LIST_RECIPIENTS", 3, 0, 500),
            store_name=os.environ.get("OUTLOOK_STORE", "").strip(),
            allow_write=os.environ.get("OUTLOOK_ALLOW_WRITE", "").strip().lower() in TRUTHY,
            # Separate from allow_write so drafting can stay on while actual
            # sending is switched off. Drafts are recoverable; sends are not.
            allow_send=os.environ.get("OUTLOOK_ALLOW_SEND", "1").strip().lower() in TRUTHY,
            # Expanded here because MCP clients commonly pass %VARS% through
            # unexpanded in the server environment block.
            attachment_dir=os.path.expanduser(
                os.path.expandvars(os.environ.get("OUTLOOK_ATTACHMENT_DIR", "").strip())
            ),
            # Per attachment, not per message. 0 disables the cap.
            max_attachment_mb=_int_from_env("OUTLOOK_MAX_ATTACHMENT_MB", 20, 0, 2048),
        )

    def resolve_attachment_dir(self, dest_dir: str = "") -> str:
        """Pick the destination: explicit argument, then env, then the default.

        An explicit `dest_dir` is what lets a caller drop files straight into
        its own working area - an agent session folder, say - which the server
        cannot know about on its own.
        """
        for candidate in (dest_dir.strip(), self.attachment_dir):
            if candidate:
                return os.path.abspath(os.path.expanduser(os.path.expandvars(candidate)))
        return os.path.abspath(default_attachment_dir())

    @property
    def max_attachment_bytes(self) -> int:
        return self.max_attachment_mb * 1024 * 1024

    def problems(self) -> list[str]:
        issues: list[str] = []
        if os.name != "nt":
            issues.append("Outlook COM is only available on Windows.")
        return issues

    def require_write(self) -> None:
        if not self.allow_write:
            raise OutlookWriteDisabledError(WRITE_DISABLED_MESSAGE)

    def require_attachment_write(self) -> None:
        """Gate for saving attachments to disk.

        Shares the OUTLOOK_ALLOW_WRITE switch, but says what it is actually
        about: this writes untrusted files from your mailbox onto the
        filesystem. It never changes the message.
        """
        if not self.allow_write:
            raise OutlookWriteDisabledError(
                "Saving attachments is disabled. Set OUTLOOK_ALLOW_WRITE=1 in the MCP "
                "server environment and reload the client to enable it. Attachments are "
                "files that arrived from outside, so writing them to disk is kept behind "
                "the same switch as sending mail."
            )

    def require_send(self) -> None:
        self.require_write()
        if not self.allow_send:
            raise OutlookWriteDisabledError(
                "Sending is disabled by OUTLOOK_ALLOW_SEND=0. Drafts can still be created "
                "with create_draft, which leaves the final click to you in Outlook."
            )
