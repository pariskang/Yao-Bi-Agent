from __future__ import annotations

import re
from typing import Any

FORBIDDEN_PATTERNS = {
    "final_diagnosis": [r"最终诊断", r"明确诊断", r"诊断为", r"可诊断为"],
    "patient_executable_prescription": [r"处方如下", r"完整处方", r"请按.*服用", r"每日[一二三四五六七八九十\d]+次", r"水煎服", r"疗程"],
    "dose_instruction": [r"\d+\s*g", r"\d+克", r"先煎", r"后下", r"饭后服", r"每次"],
    "replacement_for_clinician": [r"无需就医", r"不用看医生", r"可以自行", r"自行购买"],
}


def guard_tao_output(text: str, structured_output: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate Tao/Dao1 output before it can replace deterministic content."""

    violations: list[dict[str, str]] = []
    for category, patterns in FORBIDDEN_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                violations.append({"category": category, "pattern": pattern})
                break

    structured_output = structured_output or {}
    for key in ("final_diagnosis", "complete_prescription", "patient_executable_dose", "administration_instruction"):
        if structured_output.get(key):
            violations.append({"category": key, "pattern": f"structured.{key}"})

    return {
        "allowed": not violations,
        "violations": violations,
        "fallback_required": bool(violations),
        "guardrail": "no_final_diagnosis_no_patient_executable_prescription_no_dose",
    }


# Patient-directed self-administration / "skip the doctor" phrasing — forbidden for every role.
PATIENT_SELF_ADMIN_PATTERNS = [
    r"自行服用", r"自己煎", r"自行煎", r"回家.{0,6}煎", r"回家.{0,6}服", r"自行抓药", r"自行购买",
    r"无需就医", r"不用看医生", r"不必就医", r"可以自行", r"自己买药",
]


def guard_consultation(text: str, user_role: str = "clinician") -> dict[str, Any]:
    """Role-aware guard for the Tao-primary professional consultation answer.

    The clinician/researcher draft is allowed to name candidate syndromes, formula routes,
    方义 and **experience dose ranges** (the whole point of a teaching/research note) — but
    may never tell the patient to self-medicate or skip the physician. For the patient role
    we keep the strict floor (no diagnosis / prescription / executable dose at all).
    """

    if user_role == "patient":
        return guard_tao_output(text)

    violations: list[dict[str, str]] = []
    for pattern in PATIENT_SELF_ADMIN_PATTERNS + FORBIDDEN_PATTERNS["replacement_for_clinician"]:
        if re.search(pattern, text, flags=re.IGNORECASE):
            violations.append({"category": "patient_self_administration", "pattern": pattern})
            break
    return {
        "allowed": not violations,
        "violations": violations,
        "fallback_required": bool(violations),
        "guardrail": "clinician_research_draft_no_patient_self_administration",
    }


def guard_probe(text: str) -> dict[str, Any]:
    """Probes are questions only: block any diagnosis verdict / prescription / dose leakage."""

    bad = (
        FORBIDDEN_PATTERNS["final_diagnosis"]
        + FORBIDDEN_PATTERNS["patient_executable_prescription"]
        + FORBIDDEN_PATTERNS["dose_instruction"]
    )
    for pattern in bad:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return {"allowed": False, "violations": [{"category": "probe_leak", "pattern": pattern}]}
    return {"allowed": True, "violations": []}
