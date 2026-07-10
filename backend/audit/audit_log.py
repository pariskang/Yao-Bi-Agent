"""Append-only decision audit log + in-memory metrics counters.

Accountability layer of the CDSS governance loop: every API decision (routing,
guard verdicts, fallbacks, safety levels, physician feedback) is appended as one
JSON line to a daily file, so a reviewer can reconstruct *why* the system said
what it said — without storing raw patient narratives (free text is recorded as
a salted-free SHA-256 digest + length only).

Configuration (env):
  YAOBI_AUDIT=0        disable file writes entirely (counters still work)
  YAOBI_AUDIT_DIR=...  directory for audit files (default <repo>/logs, gitignored)

The writer is failure-safe by design: an unwritable disk must never break a
clinical-facing request, so all IO errors are swallowed after being counted.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
from threading import Lock
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# Free text above this length is elided from audit payloads (digest kept).
_MAX_TEXT = 200


def text_digest(text: str) -> dict[str, Any]:
    """Privacy-preserving reference to free text: digest + length, not content."""

    raw = (text or "").encode("utf-8")
    return {"sha256_16": hashlib.sha256(raw).hexdigest()[:16], "chars": len(text or "")}


class Counters:
    """Thread-safe in-memory counters for /api/metrics (reset on process restart)."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: Counter[str] = Counter()
        self.started_at = time.time()

    def increment(self, name: str, by: int = 1) -> None:
        with self._lock:
            self._counts[name] += by

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


_GENESIS_HASH = "0" * 16


class AuditLog:
    """Hash-chained append-only audit: each record carries ``prev_event_hash`` and its
    own ``event_hash`` over the canonical record content, so post-hoc edits or
    deletions inside a process's chain are detectable with :func:`verify_chain`.
    (Per-process chain — a restart starts a new chain from the genesis hash; a
    durable cross-restart chain is a production deployment concern.)"""

    def __init__(self, directory: str | os.PathLike[str] | None = None, enabled: bool | None = None) -> None:
        if enabled is None:
            enabled = os.getenv("YAOBI_AUDIT", "1").lower() not in {"0", "false", "off"}
        self.enabled = enabled
        self.directory = Path(directory or os.getenv("YAOBI_AUDIT_DIR") or (ROOT / "logs"))
        self._lock = Lock()
        self._seq = 0
        self._prev_hash = _GENESIS_HASH
        self.write_errors = 0

    def _path(self) -> Path:
        day = time.strftime("%Y%m%d", time.gmtime())
        return self.directory / f"audit-{day}.jsonl"

    def record(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Append one audit event; returns the record, or None when disabled/failed."""

        if not self.enabled:
            return None
        with self._lock:
            self._seq += 1
            record = {
                "ts": round(time.time(), 3),
                "seq": self._seq,
                "event": event_type,
                **payload,
            }
            record["prev_event_hash"] = self._prev_hash
            canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
            record["event_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
            self._prev_hash = record["event_hash"]
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                with self._path().open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            except OSError:
                # Audit must never break a clinical-facing request.
                self.write_errors += 1
                return None
        return record


def verify_chain(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify a contiguous slice of one process's audit chain.

    Returns {"valid": bool, "checked": n, "first_break_seq": seq | None}. A record is
    valid iff its ``event_hash`` recomputes from its content + ``prev_event_hash`` and
    it links to the previous record's hash.
    """

    prev = records[0].get("prev_event_hash") if records else _GENESIS_HASH
    for i, record in enumerate(records):
        body = {k: v for k, v in record.items() if k != "event_hash"}
        if record.get("prev_event_hash") != prev:
            return {"valid": False, "checked": i, "first_break_seq": record.get("seq")}
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        if record.get("event_hash") != expected:
            return {"valid": False, "checked": i, "first_break_seq": record.get("seq")}
        prev = record["event_hash"]
    return {"valid": True, "checked": len(records), "first_break_seq": None}


_AUDIT: AuditLog | None = None
_COUNTERS: Counters | None = None


def get_audit_log() -> AuditLog:
    """Process-wide audit log; re-created if the env configuration changed (tests)."""

    global _AUDIT
    fresh = AuditLog()
    if _AUDIT is None or _AUDIT.directory != fresh.directory or _AUDIT.enabled != fresh.enabled:
        _AUDIT = fresh
    return _AUDIT


def get_counters() -> Counters:
    global _COUNTERS
    if _COUNTERS is None:
        _COUNTERS = Counters()
    return _COUNTERS
