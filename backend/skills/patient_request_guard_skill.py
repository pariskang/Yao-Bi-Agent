from __future__ import annotations

from typing import Any

FINAL_DIAGNOSIS_TERMS = ["最终诊断", "确诊", "诊断结论", "final diagnosis"]
PRESCRIPTION_TERMS = ["完整处方", "开方", "处方", "方子", "prescription"]
DOSE_TERMS = ["剂量", "几克", "怎么服", "每日", "patient executable", "自服"]

# Medication-management requests (stop / taper / switch / administration how-tos).
# These are patient-executable decisions with real harm potential — especially
# anticoagulant changes — and must never be answered online.
MEDICATION_CHANGE_TERMS = [
    "停药", "减药", "减量", "加量", "换药", "怎么停", "能不能停", "可以停", "要不要停",
    "继续吃吗", "还能吃吗", "吃几天", "煎多久", "先煎多久", "怎么煎", "怎么吃药",
    "饭前服", "饭后服", "饭前吃", "饭后吃", "饭前还是饭后",
]
# High-risk drugs: any change/administration question about them is blocked outright.
HIGH_RISK_DRUG_TERMS = ["利伐沙班", "华法林", "阿司匹林", "氯吡格雷", "抗凝药", "泼尼松", "地塞米松", "激素"]
_DRUG_ACTION_MARKERS = ["停", "换", "减", "加量", "还能", "继续", "怎么服", "怎么吃", "服用方法", "吃法", "用法"]

MEDICATION_CHANGE_MESSAGE = (
    "涉及抗凝药、止痛药、激素或中药的停药、减量、换药与服用方法调整，"
    "不能在线自行决定——请联系开具处方的医生或线下就诊复核。"
)


def _is_medication_change_request(text: str) -> bool:
    if any(term in text for term in MEDICATION_CHANGE_TERMS):
        return True
    # A high-risk drug plus an action word ("利伐沙班能不能停") is a change request even
    # without the exact phrasing above; a bare drug mention in a symptom narrative is not.
    if any(drug.lower() in text for drug in HIGH_RISK_DRUG_TERMS):
        return any(marker in text for marker in _DRUG_ACTION_MARKERS)
    return False


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
    if _is_medication_change_request(text):
        requested.append("medication_change_request")
    blocked = bool(requested)
    if "medication_change_request" in requested:
        message = MEDICATION_CHANGE_MESSAGE
    elif blocked:
        message = "不能生成最终诊断、完整处方或患者可执行剂量；可以生成标准医案、候选证型/鉴别方向、方剂路线信号、药物模块解释和医生复核清单。"
    else:
        message = "请求未触发自动诊断/处方禁区，可继续生成医案整理和医生复核材料。"
    return {
        "requested_outputs": requested,
        "blocked": blocked,
        "message": message,
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
            "medication_change_instruction",
        ],
    }
