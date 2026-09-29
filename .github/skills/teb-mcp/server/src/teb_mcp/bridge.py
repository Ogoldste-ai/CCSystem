"""64-bit side of the worker bridge.

Spawns the 32-bit worker, exchanges JSON-lines requests and responses, and
enforces a timeout on every call.

The timeout matters more than usual here. The TEB DLL talks to hardware over
USB or TCP/IP, and a wedged board or an unreachable CE machine can block inside
a single call indefinitely. Because a hung worker would otherwise hang the MCP
server - and with it the agent - a timed-out call kills the worker and the next
call transparently starts a fresh one.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from typing import Any

WORKER_SCRIPT = os.path.join(os.path.dirname(__file__), "worker", "teb_worker.py")


class WorkerError(RuntimeError):
    """The worker reported a failure, or could not be reached."""


class TebBridge:
    """Owns a single worker subprocess and serializes access to it."""

    def __init__(self, config):
        self.config = config
        self._proc: subprocess.Popen | None = None
        self._responses: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._next_id = 0

    # -- process management ------------------------------------------------

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.running:
            return

        python32 = self.config.python32
        if not python32:
            raise WorkerError(
                "No 32-bit Python configured. TEB_If.dll is 32-bit and cannot "
                "be loaded by the 64-bit server process. Set TEB_PYTHON32 to a "
                "32-bit python.exe (see the skill README)."
            )
        if not os.path.exists(python32):
            raise WorkerError("TEB_PYTHON32 does not exist: %s" % python32)
        if not os.path.exists(WORKER_SCRIPT):
            raise WorkerError("worker script missing: %s" % WORKER_SCRIPT)

        env = os.environ.copy()
        if self.config.dll_path:
            env["TEB_DLL_PATH"] = self.config.dll_path
        if self.config.worker_log:
            env["TEB_WORKER_LOG"] = self.config.worker_log

        try:
            self._proc = subprocess.Popen(
                [python32, WORKER_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                text=False,
                bufsize=0,
            )
        except OSError as exc:
            raise WorkerError("could not start worker: %s" % exc) from exc

        self._responses = queue.Queue()
        self._reader = threading.Thread(
            target=self._read_loop, args=(self._proc,), daemon=True
        )
        self._reader.start()

    def _read_loop(self, proc: subprocess.Popen) -> None:
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    self._responses.put(json.loads(line))
                except ValueError:
                    # The worker redirects the DLL's stdout away from this pipe,
                    # so anything unparseable is unexpected; surface it rather
                    # than silently dropping it.
                    self._responses.put(
                        {"ok": False, "error": "unparseable worker output: %r" % line}
                    )
        except Exception:
            pass
        finally:
            self._responses.put(None)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return

        if proc.poll() is None:
            try:
                proc.stdin.write(b'{"id":0,"command":"shutdown"}\n')
                proc.stdin.flush()
                proc.wait(timeout=5)
            except Exception:
                pass

        if proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass

        for stream in (proc.stdin, proc.stdout):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass

    # -- request / response ------------------------------------------------

    def call(
        self, command: str, timeout: float | None = None, **args: Any
    ) -> dict[str, Any]:
        with self._lock:
            if not self.running:
                self.start()

            timeout = timeout or self.config.call_timeout
            self._next_id += 1
            req_id = self._next_id
            payload = json.dumps(
                {"id": req_id, "command": command, "args": args}
            ).encode("utf-8")

            proc = self._proc
            assert proc is not None

            try:
                proc.stdin.write(payload + b"\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._stop_locked()
                raise WorkerError("worker died before %s: %s" % (command, exc)) from exc

            # Drain stale responses from an earlier timed-out call.
            while True:
                try:
                    response = self._responses.get(timeout=timeout)
                except queue.Empty:
                    self._stop_locked()
                    raise WorkerError(
                        "%s timed out after %.0fs - the board or link is "
                        "unresponsive. The worker was restarted; the TEB "
                        "session is gone and you must connect() again."
                        % (command, timeout)
                    ) from None

                if response is None:
                    self._stop_locked()
                    raise WorkerError(
                        "worker exited unexpectedly during %s" % command
                    )

                if response.get("id") in (req_id, None):
                    break

            if not response.get("ok"):
                raise WorkerError(response.get("error") or "unknown worker error")

            return response.get("result") or {}

    def __enter__(self) -> "TebBridge":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()
