"""Minimal SQLite state store: approvals and run events survive process restarts.

Third consecutive external review to flag in-memory-only state; this is the
deliberately small first step (stdlib ``sqlite3``, one file, two tables):

* ``approvals`` — a pending emergency-override approval created before a restart
  can still be confirmed by the same physician afterwards;
* ``run_events`` — append-only run lifecycle records (RUN_*, APPROVAL_*), the
  seed for later checkpoint/replay work.

Configuration: ``YAOBI_STATE_DB`` sets the database path (default
``<repo>/logs/state.db``); ``YAOBI_STATE_DB=0`` disables persistence entirely
(pure in-memory managers, used by most unit tests implicitly via tmp dirs).
Interview *sessions* remain in-memory by design for now — documented roadmap.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from threading import Lock
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    decided_at  REAL
);
CREATE TABLE IF NOT EXISTS run_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT,
    event_type TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


class EventStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    # -- approvals ---------------------------------------------------------------
    def save_approval(self, record: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO approvals (approval_id, status, payload, created_at, decided_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (record["approval_id"], record["status"], json.dumps(record, ensure_ascii=False, default=str),
                 record.get("created_at") or time.time(), record.get("decided_at")),
            )

    def load_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT payload FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    # -- run events ---------------------------------------------------------------
    def append_event(self, event_type: str, payload: dict[str, Any], run_id: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO run_events (run_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                (run_id, event_type, json.dumps(payload, ensure_ascii=False, default=str), time.time()),
            )

    def events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT event_type, payload, created_at FROM run_events WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [{"event_type": r["event_type"], "created_at": r["created_at"], **json.loads(r["payload"])} for r in rows]


_STORE: EventStore | None = None
_STORE_DISABLED = object()
_STORE_CACHE: Any = None


def get_event_store() -> EventStore | None:
    """Process-wide store; None when persistence is disabled (YAOBI_STATE_DB=0)."""

    global _STORE_CACHE
    configured = os.getenv("YAOBI_STATE_DB", str(ROOT / "logs" / "state.db"))
    if configured.strip() in {"0", "off", "false", ""}:
        return None
    if _STORE_CACHE is not None and str(_STORE_CACHE.path) == configured:
        return _STORE_CACHE
    try:
        _STORE_CACHE = EventStore(configured)
    except (OSError, sqlite3.Error):
        return None
    return _STORE_CACHE
