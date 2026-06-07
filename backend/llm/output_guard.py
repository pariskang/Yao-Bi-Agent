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
