from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import anyio
from anyio.abc import Process
from anyio.streams.buffered import BufferedByteReceiveStream

from .config import TeamsConfig, TeamsConfigError
from .models import Message, parse_timestamp

SCAN_TIMEOUT_SECONDS = 3.0
_MAX_EVENT_BYTES = 16 * 1024 * 1024


class FileDropScanError(RuntimeError):
    """The inbox could not be read completely or the scanner failed."""


@dataclass(slots=True)
class ScanResult:
    messages: list[Message] = field(default_factory=list)
    files_scanned: int = 0
    deferred_files: int = 0
    unreadable_files: int = 0
    invalid_files: int = 0
    finished: bool = False
    timed_out: bool = False
    elapsed_ms: float = 0.0

    @property
    def complete(self) -> bool:
        return self.finished and not (
            self.timed_out or self.deferred_files or self.unreadable_files or self.invalid_files
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "files_scanned": self.files_scanned,
            "deferred_files": self.deferred_files,
            "unreadable_files": self.unreadable_files,
            "invalid_files": self.invalid_files,
            "timed_out": self.timed_out,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }

    def warning(self) -> str:
        return (
            "Incomplete Teams inbox scan: "
            f"{self.deferred_files} files need downloading, "
            f"{self.unreadable_files} files could not be read, "
            f"{self.invalid_files} files contain invalid data"
            f"{'; scan deadline exceeded' if self.timed_out else ''}. "
            "Available messages may not include the latest messages. "
            "An empty partial result does not mean there are no new messages. "
            "Check OneDrive sync and use 'Always keep on this device' for the inbox; "
            "wait for downloads to finish and correct any invalid JSON before checking again."
        )

    def require_complete(self) -> None:
        if not self.complete:
            raise FileDropScanError(self.warning())

    def recent(self, since: str = "", limit: int = 50) -> list[Message]:
        cutoff = parse_timestamp(since)
        selected = sorted(
            (message for message in self.messages if cutoff is None or message.sort_key() > cutoff),
            key=lambda message: message.sort_key(),
        )
        selected.reverse()
        return selected[:limit] if limit > 0 else selected


class FileDropScanner:
    def __init__(self, config: TeamsConfig) -> None:
        self.config = config
        self._busy = False

    async def scan(self) -> ScanResult:
        if self._busy:
            raise FileDropScanError("A Teams inbox scan is already running; wait for it to finish.")
        self._busy = True
        started = time.perf_counter()
        result = ScanResult()
        process: Process | None = None
        try:
            try:
                with anyio.fail_after(SCAN_TIMEOUT_SECONDS):
                    # Finish acquiring the process handle even if the caller cancels at spawn.
                    with anyio.CancelScope(shield=True):
                        spawning = asyncio.create_task(
                            anyio.open_process(
                                [sys.executable, "-m", "teams_mcp.filedrop_scan"],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                            )
                        )
                        try:
                            process = await asyncio.shield(spawning)
                        except asyncio.CancelledError:
                            process = await asyncio.shield(spawning)
                            raise
                    assert process.stdin is not None and process.stdout is not None
                    await process.stdin.send(
                        (json.dumps(asdict(self.config), default=str) + "\n").encode("utf-8")
                    )
                    await process.stdin.aclose()
                    stream = BufferedByteReceiveStream(process.stdout)
                    while True:
                        event = json.loads(await stream.receive_until(b"\n", _MAX_EVENT_BYTES))
                        if "error" in event:
                            raise FileDropScanError(event["error"])
                        result.messages.extend(Message(**item) for item in event["messages"])
                        for name in (
                            "files_scanned", "deferred_files", "unreadable_files", "invalid_files",
                            "finished",
                        ):
                            setattr(result, name, event[name])
                        if result.finished:
                            if await process.wait() != 0:
                                raise FileDropScanError("The Teams inbox scanner exited unexpectedly.")
                            break
            except TimeoutError:
                result.timed_out = True
            except (
                anyio.EndOfStream, anyio.IncompleteRead, anyio.DelimiterNotFound,
                anyio.BrokenResourceError, OSError, ValueError, KeyError, TypeError,
            ) as exc:
                raise FileDropScanError(
                    "The Teams inbox scanner failed. Check health and the inbox configuration."
                ) from exc
        finally:
            try:
                with anyio.CancelScope(shield=True):
                    if process is not None:
                        if process.returncode is None:
                            try:
                                process.kill()
                            except ProcessLookupError:
                                pass
                        await process.aclose()
            finally:
                self._busy = False
                result.elapsed_ms = (time.perf_counter() - started) * 1000
        return result


def _worker() -> None:
    from .backends.filedrop import FileDropBackend

    payload = json.load(sys.stdin)
    for name in ("inbox_dir", "outbox_dir", "archive_dir", "state_file"):
        if payload[name] is not None:
            payload[name] = Path(payload[name])
    config = TeamsConfig(**payload)
    sent = 0

    def report(result: ScanResult) -> None:
        nonlocal sent
        event = result.diagnostics()
        event["finished"] = result.finished
        event["messages"] = [message.to_dict() for message in result.messages[sent:]]
        sent = len(result.messages)
        print(json.dumps(event, ensure_ascii=True), flush=True)

    try:
        FileDropBackend(config).scan(report)
    except (TeamsConfigError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), flush=True)


if __name__ == "__main__":
    _worker()
