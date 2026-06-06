from __future__ import annotations

from typing import Any

from backend.skills.caseguide_utils import apply_answer, load_caseguide_questions


def pain_profile_skill(case_state: dict[str, Any], answers: dict[str, Any] | None = None) -> dict[str, Any]:
    questions = load_caseguide_questions().get("pain_questions", [])
    if not answers:
        return {"questions": questions, "case_state": case_state}
    updated = case_state
    for question in questions:
        if question["id"] in answers:
            updated = apply_answer(updated, question, answers[question["id"]])
    profile = updated.get("pain_profile", {})
    return {"case_state": updated, "pain_profile": profile, "normalized_tags": updated.get("normalized_tags", [])}
