from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

MAX_SEEN_IDS = 5000


class SeenStore:
    """Remembers which message ids have already been reported.

    ``check_new_messages`` is only useful if calling it twice does not report
    the same message twice, so the ids are persisted. The list is bounded and
    trimmed oldest-first, otherwise the file would grow without limit on a busy
    account.
    """

    def __init__(self, path: Path, max_ids: int = MAX_SEEN_IDS) -> None:
        self.path = path
        self.max_ids = max_ids
        self._order: list[str] = []
        self._ids: set[str] = set()
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        ids = raw.get("seen") if isinstance(raw, dict) else raw
        if isinstance(ids, list):
            self._order = [str(item) for item in ids if item]
            self._ids = set(self._order)

    def save(self) -> None:
        """Write atomically so a crash mid-write cannot corrupt the state."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"seen": self._order[-self.max_ids :]}, indent=2)
        handle, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".seen-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as tmp:
                tmp.write(payload)
            os.replace(tmp_name, self.path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def has_seen(self, message_id: str) -> bool:
        self.load()
        return message_id in self._ids

    def mark_seen(self, message_ids: Iterable[str]) -> int:
        self.load()
        added = 0
        for message_id in message_ids:
            if not message_id or message_id in self._ids:
                continue
            self._ids.add(message_id)
            self._order.append(message_id)
            added += 1
        if len(self._order) > self.max_ids:
            dropped = self._order[: -self.max_ids]
            self._order = self._order[-self.max_ids :]
            self._ids.difference_update(dropped)
        return added

    def stats(self) -> dict[str, Any]:
        self.load()
        return {"tracked_ids": len(self._order), "state_file": str(self.path)}
