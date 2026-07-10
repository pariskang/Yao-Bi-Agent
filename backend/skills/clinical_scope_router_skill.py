"""Clinical scope router: is this case inside the system's approved task domain?

The system is a *lumbar Bi (腰痹) experience CDSS prototype*. Before any TCM reasoning,
every case must be routed: chest pain, vascular emergencies, open fractures, cervical
myelopathy and non-lumbar orthopedic complaints must never fall through into the lumbar
formula chain just because the pipeline exists. The emergency safety kernel
(red-flag gate) runs FIRST and owns resuscitation-level findings; this router then
decides whether the remaining, non-emergency case is in scope for lumbar-Bi syndrome
support or should be referred to the appropriate specialty with education-only output.

Deterministic, keyword-anchored and deliberately conservative: when no lumbar anchor is
present the case is out of scope — safety triage is the only capability that is always
allowed.
"""

from __future__ import annotations

from typing import Any

from backend.skills.clinical_entity_skill import is_affirmed
from backend.skills.safety_guard_skill import EMERGENCY_HALT_CATEGORIES

# Anchors that put a case inside the lumbar-Bi domain (腰 covers 腰痛/腰背/腰椎/腰膝…).
_LUMBAR_ANCHORS = ("腰", "坐骨神经", "臀部放射")

# Non-lumbar body-region anchors → the case belongs to another orthopedic domain.
_JOINT_ANCHORS = ("膝", "肩", "肘", "腕", "踝", "髋", "颈椎", "颈部", "手指", "足跟", "足踝")

# Trauma-domain anchors (fracture care, not lumbar Bi differentiation).
_TRAUMA_ANCHORS = ("骨折", "脱位", "车祸", "坠落", "挤压伤", "砸伤")

ALWAYS_ALLOWED = ["safety_triage"]
LUMBAR_CAPABILITIES = ["safety_triage", "lumbar_bi_syndrome_support"]


def clinical_scope_router_skill(raw_text: str, red_flag_categories: list[str] | None = None) -> dict[str, Any]:
    """Route a case narrative to a domain + allowed capability set.

    ``red_flag_categories`` are the confirmed categories from the safety grading —
    when an emergency category is present the router defers to the safety kernel
    (domain "emergency", triage only), regardless of body region.
    """

    text = raw_text or ""
    categories = set(red_flag_categories or [])
    lumbar = any(anchor in text and is_affirmed(text, anchor) for anchor in _LUMBAR_ANCHORS)
    trauma = any(anchor in text and is_affirmed(text, anchor) for anchor in _TRAUMA_ANCHORS)
    joint = any(anchor in text and is_affirmed(text, anchor) for anchor in _JOINT_ANCHORS)

    if categories & EMERGENCY_HALT_CATEGORIES:
        return {
            "domain": "emergency", "task": "triage", "in_scope": False, "scope_confidence": 0.95,
            "out_of_scope_reason": "急症安全内核已接管：先急诊/线下评估，不进入腰痹辨证。",
            "allowed_capabilities": list(ALWAYS_ALLOWED),
        }
    if lumbar:
        return {
            "domain": "spine", "task": "diagnosis_support", "in_scope": True,
            "scope_confidence": 0.9 if not (trauma or joint) else 0.75,
            "out_of_scope_reason": None,
            "allowed_capabilities": list(LUMBAR_CAPABILITIES),
        }
    if trauma:
        return {
            "domain": "trauma", "task": "triage", "in_scope": False, "scope_confidence": 0.85,
            "out_of_scope_reason": "创伤/骨折主诉不属于腰痹辨证范围，请转创伤骨科评估。",
            "allowed_capabilities": list(ALWAYS_ALLOWED),
        }
    if joint:
        return {
            "domain": "joint", "task": "triage", "in_scope": False, "scope_confidence": 0.8,
            "out_of_scope_reason": "非腰部骨伤主诉不属于本系统获准的腰痹任务域，请至相应专科面诊。",
            "allowed_capabilities": list(ALWAYS_ALLOWED),
        }
    return {
        "domain": "unknown", "task": "triage", "in_scope": False, "scope_confidence": 0.5,
        "out_of_scope_reason": "未识别到腰痹相关主诉，无法确认属于本系统任务域。",
        "allowed_capabilities": list(ALWAYS_ALLOWED),
    }
