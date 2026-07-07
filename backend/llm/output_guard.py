from __future__ import annotations

import re
from typing import Any

from backend.contracts import PATIENT_VIEW, validate

# Chinese numerals that appear in colloquial dose / frequency instructions ("三克"、"一日三次").
_CHN_NUM = "一二三四五六七八九十两半"

FORBIDDEN_PATTERNS = {
    "final_diagnosis": [r"最终诊断", r"明确诊断", r"诊断为", r"可诊断为", r"确诊为"],
    "patient_executable_prescription": [
        r"处方如下",
        r"完整处方",
        r"请按.*服用",
        r"水煎服",
        # Frequency instructions in Arabic or Chinese numerals: 每日2次 / 一日三次 / 每天三服 / 日3次.
        rf"[每一]?[日天]\s*[{_CHN_NUM}\d]+\s*[次服]",
        rf"分[{_CHN_NUM}\d]+次",
        # Numbered course of treatment ("两个疗程"), not the bare teaching word 疗程.
        rf"[{_CHN_NUM}\d]+\s*个?疗程",
    ],
    "dose_instruction": [
        # Arabic-digit doses: 3g / 3 克 / 500mg / 3钱 (excludes alphabetic runs like "IgG4").
        r"\d+(?:\.\d+)?\s*(?:g(?![a-zA-Z])|克|mg(?![a-zA-Z])|毫克|钱)",
        # Chinese-numeral doses: 三克 / 两钱 — the classic bypass of digit-only regexes.
        rf"[{_CHN_NUM}]+\s*[克钱]",
        r"先煎",
        r"后下",
        r"饭后服",
        # Per-dose instructions ("每次一袋/每次服6克"), not innocent phrases like "每次复诊".
        rf"每次[^，。;；\n]{{0,6}}(?:\d|[{_CHN_NUM}]|服|克|丸|片|袋)",
    ],
    "replacement_for_clinician": [r"无需就医", r"不用看医生", r"可以自行", r"自行购买"],
}

# Structured JSON contract: these keys must stay null in every Tao JSON overlay.
_FORBIDDEN_STRUCTURED_KEYS = (
    "final_diagnosis",
    "complete_prescription",
    "patient_executable_dose",
    "administration_instruction",
)


def _structured_violations(structured_output: dict[str, Any] | None) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for key in _FORBIDDEN_STRUCTURED_KEYS:
        if (structured_output or {}).get(key):
            violations.append({"category": key, "pattern": f"structured.{key}"})
    return violations


def guard_tao_output(text: str, structured_output: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strict patient-floor guard: no diagnosis, prescription, or executable dose at all."""

    violations: list[dict[str, str]] = []
    for category, patterns in FORBIDDEN_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                violations.append({"category": category, "pattern": pattern})
                break

    violations.extend(_structured_violations(structured_output))

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

# Content forbidden even in a clinician-facing draft: assertive final verdicts and
# complete executable regimens. Experience dose *ranges*, 方义, 先煎/后下 safety notes
# and the bare word 疗程 are deliberately allowed — that is the point of a teaching draft.
_CLINICIAN_DRAFT_FORBIDDEN = [
    (r"最终诊断|明确诊断|确诊为", "assertive_final_diagnosis"),
    (r"处方如下|完整处方|请按.*服用", "complete_prescription"),
    (rf"水煎服|[每一][日天]\s*[{_CHN_NUM}\d]+\s*[次服]|分[{_CHN_NUM}\d]+次(?:服|口服)", "executable_regimen"),
]


def guard_clinician_draft(text: str, structured_output: dict[str, Any] | None = None) -> dict[str, Any]:
    """Soft guard for clinician/research Tao overlays (report / reasoning / experience notes).

    A clinician draft may name candidate syndromes, formula routes, 方义 and experience
    dose ranges ("细辛经验剂量 3-6g，医师审核") — those are what a teaching note is for.
    It may not assert a final diagnosis, issue a complete executable regimen, or tell
    the patient to self-medicate / skip the physician.
    """

    violations: list[dict[str, str]] = []
    for pattern in PATIENT_SELF_ADMIN_PATTERNS + FORBIDDEN_PATTERNS["replacement_for_clinician"]:
        if re.search(pattern, text, flags=re.IGNORECASE):
            violations.append({"category": "patient_self_administration", "pattern": pattern})
            break
    for pattern, category in _CLINICIAN_DRAFT_FORBIDDEN:
        if re.search(pattern, text, flags=re.IGNORECASE):
            violations.append({"category": category, "pattern": pattern})

    violations.extend(_structured_violations(structured_output))

    return {
        "allowed": not violations,
        "violations": violations,
        "fallback_required": bool(violations),
        "guardrail": "clinician_draft_no_final_verdict_no_executable_regimen_no_self_administration",
    }


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


# ------------------------------------------------------------------ patient payload floor
# Strict whitelist of turn fields a patient-facing API response may expose. Everything
# else (clinician drafts, herb modules, rule traces, dose statistics…) is dropped
# server-side — the patient view is an allowlist, not a blocklist. The agent trace is
# deliberately NOT whitelisted: it carries sub-agent observations, skill names and
# intermediate clinical reasoning, any of which could leak clinician-grade content the
# moment an upstream skill forgets to role-filter.
PATIENT_TURN_VISIBLE_FIELDS = (
    "question", "intent", "intent_label", "blocked", "disclaimer",
    "suggested_followups", "safety_notice",
)

_PATIENT_GUARDED_FALLBACK = (
    "为了您的安全，这部分内容需要执业医师当面评估后才能提供。"
    "如腰痛持续加重、夜间痛明显、伴发热、外伤后疼痛或大小便异常，请尽快线下就诊。"
)


def filter_patient_payload(turn: dict[str, Any]) -> dict[str, Any]:
    """Reduce a turn payload to the patient-visible structured schema.

    The answer text must still pass the strict patient guard — a clinician-grade
    draft that leaked into a patient turn is replaced by the safe fallback. Fields
    like ``medication_advice`` are pinned to ``null`` by construction so no upstream
    change can accidentally expose prescribing content to patients.
    """

    answer = str(turn.get("answer") or "")
    guard = guard_tao_output(answer)
    filtered: dict[str, Any] = {key: turn[key] for key in PATIENT_TURN_VISIBLE_FIELDS if key in turn}
    filtered.update({
        "role": "patient",
        "patient_visible_message": answer if guard["allowed"] else _PATIENT_GUARDED_FALLBACK,
        "answer": answer if guard["allowed"] else _PATIENT_GUARDED_FALLBACK,
        "forbidden_content_detected": not guard["allowed"],
        "guard_violations": [v["category"] for v in guard["violations"]],
        "requires_doctor_review": True,
        "medication_advice": None,
        "clinician_draft": None,
        "answer_source": "patient_safe_view",
    })
    return validate(filtered, PATIENT_VIEW, "output_guard.filter_patient_payload")


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
