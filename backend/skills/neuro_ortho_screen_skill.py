from __future__ import annotations

from typing import Any

from backend.skills.caseguide_utils import apply_answer, load_caseguide_questions


def neuro_ortho_screen_skill(case_state: dict[str, Any], answers: dict[str, Any] | None = None) -> dict[str, Any]:
    questions = load_caseguide_questions().get("neuro_ortho_questions", [])
    if not answers:
        return {"questions": questions, "case_state": case_state}
    updated = case_state
    urgent = []
    for question in questions:
        if question["id"] in answers:
            answer = answers[question["id"]]
            updated = apply_answer(updated, question, answer)
            if answer in (question.get("urgent_if") or []):
                urgent.append(question["question"])
    return {"case_state": updated, "neuro_ortho": updated.get("neuro_ortho", {}), "urgent_neuro_ortho_flags": urgent}
