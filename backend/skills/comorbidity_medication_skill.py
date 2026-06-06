from __future__ import annotations

from typing import Any

from backend.skills.caseguide_utils import apply_answer, load_caseguide_questions

NSAIDS = {"塞来昔布", "布洛芬", "双氯芬酸", "艾瑞昔布", "依托考昔"}


def comorbidity_medication_skill(case_state: dict[str, Any], answers: dict[str, Any] | None = None) -> dict[str, Any]:
    questions = load_caseguide_questions().get("comorbidity_questions", [])
    if not answers:
        return {"questions": questions, "case_state": case_state}
    updated = case_state
    for question in questions:
        if question["id"] in answers:
            updated = apply_answer(updated, question, answers[question["id"]])
    comorbidity = updated.get("comorbidity", {})
    meds = set(comorbidity.get("medications") or [])
    diseases = set(comorbidity.get("diseases") or [])
    safety_notes = []
    if meds & NSAIDS:
        safety_notes.append("已有NSAIDs使用史，需医生关注胃肠道和肾功能风险。")
    if "乙哌立松" in meds:
        safety_notes.append("已有肌松药使用史，需医生复核嗜睡、肝功能等风险。")
    if "骨质疏松" in diseases:
        safety_notes.append("骨质疏松为补肝肾强筋骨模块的重要背景信息。")
    if comorbidity.get("anticoagulant_or_steroid") in {"是", "不确定"}:
        safety_notes.append("抗凝药、阿司匹林、激素或降糖药使用情况需医生核对。")
    return {"case_state": updated, "comorbidities": list(diseases), "current_medications": list(meds), "safety_notes": safety_notes}
