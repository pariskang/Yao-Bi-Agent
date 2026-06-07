from __future__ import annotations

from typing import Any

FINAL_DIAGNOSIS_TERMS = ["最终诊断", "确诊", "诊断结论", "final diagnosis"]
PRESCRIPTION_TERMS = ["完整处方", "开方", "处方", "方子", "prescription"]
DOSE_TERMS = ["剂量", "几克", "怎么服", "每日", "patient executable", "自服"]


def patient_request_guard_skill(user_request: str, user_role: str = "patient") -> dict[str, Any]:
    """Classify and block requests for autonomous diagnosis/prescribing.

    The project can produce clinician-review hypotheses and non-prescriptive
    experience modules. It must not produce final diagnoses, complete
    prescriptions, or patient-executable doses, even if labeled as requiring
    doctor review.
    """
    text = user_request.lower()
    requested = []
    if any(term.lower() in text for term in FINAL_DIAGNOSIS_TERMS):
        requested.append("final_diagnosis")
    if any(term.lower() in text for term in PRESCRIPTION_TERMS):
        requested.append("complete_prescription")
    if any(term.lower() in text for term in DOSE_TERMS):
        requested.append("patient_executable_dose")
    blocked = bool(requested)
    return {
        "requested_outputs": requested,
        "blocked": blocked,
        "message": (
            "不能生成最终诊断、完整处方或患者可执行剂量；可以生成标准医案、候选证型/鉴别方向、方剂路线信号、药物模块解释和医生复核清单。"
            if blocked
            else "请求未触发自动诊断/处方禁区，可继续生成医案整理和医生复核材料。"
        ),
        "safe_next_action": "clinician_review_package" if blocked else "continue_case_collection",
        "allowed_outputs": [
            "standard_case",
            "structured_tags",
            "risk_flags",
            "clinician_review_differentials",
            "tcm_pattern_hypotheses",
            "formula_route_signals_non_prescriptive",
            "herb_module_explanations_without_dose",
            "clinician_handoff_checklist",
        ],
        "forbidden_outputs": [
            "final_diagnosis",
            "complete_clinical_prescription",
            "patient_executable_dose",
            "self_medication_plan",
        ],
    }
