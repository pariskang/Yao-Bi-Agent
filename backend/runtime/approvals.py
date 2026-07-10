"""First-class approval objects for high-risk human-in-the-loop actions.

An emergency-referral override is the highest-risk action the system supports:
it clears confirmed red flags and resumes clinical questioning. Before this
module it was a bare ``review_action="override"`` string plus free-text reason.
Now it is a two-phase, attributable approval:

1. request phase — requires an authenticated clinician role, a ``reviewer_id``
   and a non-empty reason; creates a *pending* :class:`ApprovalRequest` and does
   NOT change clinical state;
2. confirm phase — the same reviewer re-submits with the approval id and the
   explicit confirmation flag; only then is the approval marked approved and the
   action executed.

Every phase is recorded in the audit log (which is hash-chained, see
``backend/audit/audit_log.py``), so who overrode which red flags, when and why
is reconstructible. Storage is in-memory per process — matching the interview
session store it protects; durable storage is a deployment concern documented
in docs/harness_review_response_2026-07.md.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any

from backend.audit import get_audit_log

# Risk tiers for reviewed actions (mirrors the review-requirement table in docs).
RISK_LEVELS = {"confirm_referral": "standard", "revise_referral": "standard", "override_emergency_referral": "critical"}


@dataclass
class ApprovalRequest:
    action_type: str
    session_id: str
    required_role: str = "clinician"
    reviewer_id: str = ""
    reason: str = ""
    risk_level: str = "critical"
    status: str = "pending"          # pending | approved | rejected | expired
    payload: dict[str, Any] = field(default_factory=dict)
    approval_id: str = field(default_factory=lambda: f"apr-{uuid.uuid4().hex[:12]}")
    created_at: float = field(default_factory=time.time)
    decided_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ApprovalManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: dict[str, ApprovalRequest] = {}

    def create(self, *, action_type: str, session_id: str, reviewer_id: str, reason: str,
               payload: dict[str, Any] | None = None) -> ApprovalRequest:
        request = ApprovalRequest(
            action_type=action_type,
            session_id=session_id,
            reviewer_id=reviewer_id,
            reason=reason,
            risk_level=RISK_LEVELS.get(action_type, "critical"),
            payload=payload or {},
        )
        with self._lock:
            self._requests[request.approval_id] = request
        get_audit_log().record("approval_requested", {
            "approval_id": request.approval_id, "action_type": action_type,
            "session_id": session_id, "reviewer_id": reviewer_id,
            "risk_level": request.risk_level, "reason": reason[:300],
            "payload": payload or {},
        })
        return request

    def get(self, approval_id: str) -> ApprovalRequest | None:
        with self._lock:
            return self._requests.get(approval_id)

    def decide(self, approval_id: str, *, decision: str, reviewer_id: str) -> ApprovalRequest | None:
        """Approve/reject a pending request. The confirming reviewer must match the requester."""

        with self._lock:
            request = self._requests.get(approval_id)
            if request is None or request.status != "pending":
                return None
            if reviewer_id != request.reviewer_id:
                # A different human cannot silently complete someone else's override.
                return None
            request.status = "approved" if decision == "approve" else "rejected"
            request.decided_at = time.time()
        get_audit_log().record("approval_decided", {
            "approval_id": approval_id, "action_type": request.action_type,
            "session_id": request.session_id, "reviewer_id": reviewer_id,
            "decision": request.status,
        })
        return request


_MANAGER: ApprovalManager | None = None


def get_approval_manager() -> ApprovalManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = ApprovalManager()
    return _MANAGER
