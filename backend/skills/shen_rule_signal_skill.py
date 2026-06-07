from __future__ import annotations

from typing import Any


def shen_rule_signal_skill(case_state: dict[str, Any]) -> dict[str, Any]:
    tags = set(case_state.get("normalized_tags") or [])
    profile = case_state.get("patient_profile", {})
    chief = case_state.get("chief_complaint", {})
    signals = {
        "danggui_sini_signal": bool(tags & {"lower_limb_numbness", "radiating_leg_pain"}),
        "cold_damp_signal": {"cold_aggravation", "warmth_relieves"}.issubset(tags) or "cold_damp_signal" in tags,
        "bushen_bone_signal": bool(tags & {"osteoporosis", "elderly", "lumbar_knee_soreness"}),
        "chaihu_signal": bool(tags & {"bitter_taste", "dry_mouth"}) and "insomnia" in tags,
        "stomach_protection_signal": bool(tags & {"poor_appetite", "weak_stomach", "epigastric_discomfort", "nausea"}),
        "qixue_bizhu_damp_signal": bool(tags & {"dark_tongue", "white_greasy_coating", "greasy_coating"}) and "chronic_yabi" in tags,
    }
    age = profile.get("age")
    if isinstance(age, int):
        signals["young_patient"] = age <= 40
        signals["elderly"] = age >= 60
        signals["very_elderly"] = age >= 73
    duration = chief.get("duration") or ""
    signals["long_duration"] = any(unit in str(duration) for unit in ["年", "多年"])
    high_value_missing = []
    if not case_state.get("tcm_inquiry", {}).get("tongue", {}).get("color"):
        high_value_missing.append("舌象未采集")
    if not case_state.get("tcm_inquiry", {}).get("sleep"):
        high_value_missing.append("睡眠情况未采集")
    if not case_state.get("tcm_inquiry", {}).get("appetite"):
        high_value_missing.append("胃纳情况未采集")
    if not case_state.get("neuro_ortho", {}).get("imaging"):
        high_value_missing.append("影像/骨密度信息未采集")
    updated = dict(case_state)
    updated["shen_rule_signals"] = signals
    return {"case_state": updated, "shen_signals": signals, "high_value_missing": high_value_missing}
