from __future__ import annotations

from typing import Any

from backend.skills.caseguide_utils import get_path, is_missing

QUALITY_DIMENSIONS = {
    "basic_info": {"fields": ["patient_profile.age", "patient_profile.sex", "chief_complaint.standard_text", "chief_complaint.duration"], "weight": 20},
    "pain_profile": {"fields": ["pain_profile.location", "pain_profile.radiation", "pain_profile.pain_nature", "pain_profile.severity_0_10", "pain_profile.aggravating_factors", "pain_profile.relieving_factors"], "weight": 20},
    "red_flag": {"fields": ["red_flags.status"], "weight": 20},
    "tcm_features": {"fields": ["tcm_inquiry.cold_heat", "tcm_inquiry.dampness", "tcm_inquiry.fatigue", "tcm_inquiry.sleep", "tcm_inquiry.appetite", "tcm_inquiry.stool", "tcm_inquiry.urine", "tcm_inquiry.tongue.color", "tcm_inquiry.tongue.coating", "tcm_inquiry.pulse"], "weight": 20},
    "shen_rule_signals": {"fields": ["neuro_ortho.numbness", "tcm_inquiry.cold_pain_relation", "comorbidity.diseases", "tcm_inquiry.mouth_taste", "tcm_inquiry.appetite", "tcm_inquiry.tongue.coating"], "weight": 20},
}

FOLLOWUP_QUESTION_BY_FIELD = {
    "tcm_inquiry.pulse": "脉象由医生面诊补充；如有既往记录，可填写。",
    "neuro_ortho.imaging": "是否做过腰椎MRI、CT、X线或骨密度检查？",
    "tcm_inquiry.tongue.color": "舌头颜色偏淡、偏暗紫还是偏红？",
    "tcm_inquiry.sleep": "睡眠怎么样，是否入睡困难、易醒或多梦？",
    "tcm_inquiry.appetite": "胃口怎么样，吃药是否容易胃不舒服？",
    "pain_profile.radiation": "腰痛是否会放射到臀部、大腿、小腿或足部？",
    "neuro_ortho.weakness": "是否有下肢无力、走路拖脚或逐渐加重？",
}


def case_quality_check_skill(case_state: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    missing_critical_fields: list[str] = []
    dimension_scores: dict[str, float] = {}
    for name, cfg in QUALITY_DIMENSIONS.items():
        fields = cfg["fields"]
        present = [field for field in fields if not is_missing(get_path(case_state, field))]
        dim_score = cfg["weight"] * len(present) / len(fields)
        dimension_scores[name] = round(dim_score, 1)
        score += dim_score
        missing_critical_fields.extend(field for field in fields if field not in present)
    recommended = []
    for field in missing_critical_fields:
        if field in FOLLOWUP_QUESTION_BY_FIELD and FOLLOWUP_QUESTION_BY_FIELD[field] not in recommended:
            recommended.append(FOLLOWUP_QUESTION_BY_FIELD[field])
    rounded = int(round(score))
    grade = "excellent" if rounded >= 90 else "good" if rounded >= 75 else "fair" if rounded >= 60 else "needs_more_info"
    updated = dict(case_state)
    updated["case_quality_score"] = rounded
    updated["missing_fields"] = missing_critical_fields
    return {
        "case_state": updated,
        "case_quality_score": rounded,
        "grade": grade,
        "dimension_scores": dimension_scores,
        "missing_critical_fields": missing_critical_fields,
        "recommended_followup_questions": recommended[:5],
    }
