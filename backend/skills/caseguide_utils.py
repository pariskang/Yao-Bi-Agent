from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.engine.rule_engine import RULES_DIR, load_yaml

CASE_GUIDE_QUESTIONS = RULES_DIR / "10_case_guide_questions.yaml"


def empty_case_state() -> dict[str, Any]:
    return {
        "case_id": "auto_generated",
        "patient_profile": {"age": None, "sex": None, "occupation": None, "physical_labor": None},
        "chief_complaint": {"main_symptom": None, "duration": None, "acute_worsening": None, "recurrent_status": None, "standard_text": None},
        "pain_profile": {"location": [], "radiation": None, "pain_nature": [], "severity_0_10": None, "aggravating_factors": [], "relieving_factors": []},
        "neuro_ortho": {"numbness": None, "numbness_location": [], "weakness": None, "walking_limitation": None, "bowel_bladder": None, "imaging": [], "western_diagnosis": []},
        "tcm_inquiry": {
            "cold_heat": None, "cold_pain_relation": None, "cold_extremities": None, "dampness": None,
            "fatigue": None, "lumbar_knee_soreness": None, "sleep": None, "appetite": None,
            "mouth_taste": None, "sweating": None, "stool": None, "urine": None, "menstruation": None,
            "tongue": {"color": None, "coating": None, "photo_uploaded": False}, "pulse": None,
        },
        "comorbidity": {"diseases": [], "medications": [], "anticoagulant_or_steroid": None, "allergy": None},
        "red_flags": {"status": None, "positive_items": []},
        "normalized_tags": [],
        "shen_rule_signals": {},
        "missing_fields": [],
        "case_quality_score": None,
        "asked_question_ids": [],
        "answer_evidence": {},
    }


def load_caseguide_questions() -> dict[str, Any]:
    return load_yaml(CASE_GUIDE_QUESTIONS) or {}


def all_questions() -> list[dict[str, Any]]:
    data = load_caseguide_questions()
    questions: list[dict[str, Any]] = []
    for key, value in data.items():
        if key.endswith("_questions"):
            questions.extend(value or [])
    return questions


def get_path(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def set_path(data: dict[str, Any], dotted: str, value: Any) -> None:
    cur: Any = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    old = cur.get(parts[-1])
    if isinstance(old, list):
        if isinstance(value, list):
            cur[parts[-1]] = value
        else:
            cur[parts[-1]] = [value]
    else:
        cur[parts[-1]] = value


def is_missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == "unknown"


def normalize_answer(answer: Any) -> list[str]:
    if answer is None:
        return []
    if isinstance(answer, list):
        return [str(item) for item in answer]
    return [str(answer)]


def apply_answer(case_state: dict[str, Any], question: dict[str, Any], answer: Any) -> dict[str, Any]:
    updated = deepcopy(case_state)
    qid = question.get("id")
    if qid and qid not in updated.setdefault("asked_question_ids", []):
        updated["asked_question_ids"].append(qid)
    if question.get("field"):
        set_path(updated, question["field"], answer)
    if qid:
        updated.setdefault("answer_evidence", {})[qid] = {"question": question.get("question"), "answer": answer}
    mapped_tags = set(updated.get("normalized_tags") or [])
    tag_mapping = question.get("tag_mapping") or {}
    for item in normalize_answer(answer):
        mapped_tags.update(tag_mapping.get(item, []))
    updated["normalized_tags"] = sorted(mapped_tags)
    return updated


def format_question(question: dict[str, Any]) -> dict[str, Any]:
    keys = ["id", "stage", "question", "type", "input_type", "options", "examples", "field"]
    return {key: question[key] for key in keys if key in question}
