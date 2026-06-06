from __future__ import annotations

from typing import Any

from backend.skills.caseguide_utils import apply_answer, load_caseguide_questions


def tcm_four_diagnosis_skill(case_state: dict[str, Any], answers: dict[str, Any] | None = None) -> dict[str, Any]:
    questions = load_caseguide_questions().get("tcm_four_diagnosis_questions", [])
    if not answers:
        return {"questions": questions, "case_state": case_state}
    updated = case_state
    for question in questions:
        if question["id"] in answers:
            updated = apply_answer(updated, question, answers[question["id"]])
    return {"case_state": updated, "tcm_inquiry": updated.get("tcm_inquiry", {}), "normalized_tags": updated.get("normalized_tags", [])}
