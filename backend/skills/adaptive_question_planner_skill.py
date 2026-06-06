from __future__ import annotations

from typing import Any

from backend.skills.case_quality_check_skill import case_quality_check_skill
from backend.skills.caseguide_utils import all_questions, format_question, get_path, is_missing

HIGH_VALUE_FIELDS = {
    "red_flags.status": 100,
    "patient_profile.age": 35,
    "patient_profile.sex": 30,
    "chief_complaint.main_symptom": 45,
    "chief_complaint.duration": 45,
    "pain_profile.location": 35,
    "pain_profile.radiation": 45,
    "neuro_ortho.numbness": 50,
    "neuro_ortho.weakness": 60,
    "tcm_inquiry.cold_pain_relation": 50,
    "tcm_inquiry.sleep": 35,
    "tcm_inquiry.appetite": 35,
    "tcm_inquiry.mouth_taste": 35,
    "neuro_ortho.imaging": 35,
    "comorbidity.diseases": 40,
    "comorbidity.medications": 40,
    "tcm_inquiry.tongue.color": 30,
    "tcm_inquiry.tongue.coating": 30,
}


def adaptive_question_planner_skill(case_state: dict[str, Any], max_questions: int = 3, patient_burden_count: int | None = None) -> dict[str, Any]:
    asked = set(case_state.get("asked_question_ids") or [])
    tags = set(case_state.get("normalized_tags") or [])
    quality = case_quality_check_skill(case_state)
    candidates = []
    for question in all_questions():
        qid = question.get("id")
        if qid in asked or not question.get("field"):
            continue
        field = question["field"]
        if not is_missing(get_path(case_state, field)):
            continue
        safety_weight = 80 if qid and qid.startswith("RF") else 0
        missing_weight = HIGH_VALUE_FIELDS.get(field, 10)
        info_gain = 0
        priority_when = question.get("priority_when") or {}
        if set(priority_when.get("any") or []) & tags:
            info_gain += 25
        if field in {"tcm_inquiry.cold_pain_relation", "neuro_ortho.numbness"} and (tags & {"elderly", "chronic_yabi", "lower_limb_numbness"}):
            info_gain += 30
        if field in {"comorbidity.diseases", "tcm_inquiry.lumbar_knee_soreness"} and tags & {"elderly", "chronic_yabi"}:
            info_gain += 20
        uncertainty_weight = 15 if 55 <= quality["case_quality_score"] < 80 else 5
        burden = patient_burden_count if patient_burden_count is not None else len(asked)
        patient_burden_penalty = max(0, burden - 12) * 2
        priority = safety_weight + missing_weight + info_gain + uncertainty_weight - patient_burden_penalty
        candidates.append({"priority": priority, "question": format_question(question), "reason": f"补齐 {field}，提升医案质量和规则分流信息量"})
    candidates.sort(key=lambda item: item["priority"], reverse=True)
    return {
        "next_questions": candidates[:max_questions],
        "case_quality_score": quality["case_quality_score"],
        "ask_more": quality["case_quality_score"] < 70 and bool(candidates),
        "patient_fatigue_detected": len(asked) >= 25,
    }
