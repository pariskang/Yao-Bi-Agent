from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

HIGH_RISK_HERBS = {"附片", "细辛", "蜈蚣", "全蝎", "制川乌", "制草乌", "乌头"}
REQUIRED_REVIEW_FIELDS = ["physician_id", "physician_name", "license_id"]


def _missing_required(reviewer: dict[str, Any]) -> list[str]:
    return [field for field in REQUIRED_REVIEW_FIELDS if not reviewer.get(field)]


def create_physician_review_task(
    case_state: dict[str, Any],
    clinician_review_package: dict[str, Any] | None = None,
    requested_by: str = "system",
) -> dict[str, Any]:
    """Create a clinician-only review task.

    This module intentionally does not let the model finalize diagnosis or produce
    patient-executable prescriptions. It packages model/rule outputs for a licensed
    physician, who may then manually enter and sign clinical decisions outside the
    patient-facing generation path.
    """
    return {
        "review_task": {
            "task_id": f"physician-review-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "status": "pending_physician_review",
            "requested_by": requested_by,
            "case_state": case_state,
            "clinician_review_package": clinician_review_package or {},
            "allowed_physician_actions": [
                "confirm_or_reject_rule_hypotheses",
                "enter_final_diagnosis_manually",
                "enter_prescription_manually",
                "enter_dose_and_administration_manually",
                "add_followup_plan_manually",
                "sign_and_lock_review",
            ],
            "model_forbidden_actions": [
                "final_diagnosis_generation",
                "complete_prescription_generation",
                "patient_executable_dose_generation",
                "self_medication_instruction_generation",
            ],
            "patient_visible_until_signed": False,
        }
    }


def physician_review_skill(
    case_state: dict[str, Any],
    reviewer: dict[str, Any],
    final_diagnosis: dict[str, Any] | None = None,
    prescription: list[dict[str, Any]] | None = None,
    administration: dict[str, Any] | None = None,
    review_notes: str | None = None,
    clinician_review_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a physician-authored final diagnosis/prescription after sign-off.

    The function rejects unsigned or model-authored final clinical content. It is a
    handoff/audit module, not an autonomous prescribing model.
    """
    missing = _missing_required(reviewer)
    if missing:
        return {
            "status": "rejected_missing_physician_identity",
            "missing_fields": missing,
            "message": "最终诊断和处方只能由具备资质的医师审核并签名后录入。",
        }
    if reviewer.get("role") != "licensed_physician":
        return {
            "status": "rejected_not_physician",
            "message": "仅 licensed_physician 角色可提交最终诊断和处方审核记录。",
        }
    if not reviewer.get("signed"):
        return {
            "status": "rejected_unsigned",
            "message": "医师必须签名确认后才能锁定最终诊断和处方记录。",
        }
    if final_diagnosis and final_diagnosis.get("source") == "model_generated":
        return {
            "status": "rejected_model_generated_diagnosis",
            "message": "模型不得生成最终诊断；请由医师手工录入并签名。",
        }
    if any(item.get("source") == "model_generated" for item in prescription or []):
        return {
            "status": "rejected_model_generated_prescription",
            "message": "模型不得生成完整处方或剂量；处方必须由医师手工录入并签名。",
        }
    high_risk_hits = sorted({item.get("herb") for item in prescription or [] if item.get("herb") in HIGH_RISK_HERBS})
    warnings = []
    if high_risk_hits:
        warnings.append(f"高风险药物需重点复核：{', '.join(high_risk_hits)}。")
    if administration:
        warnings.append("煎服法、疗程和剂量为医师签名内容，不应由患者端模型自动生成。")
    record = {
        "status": "signed_physician_review",
        "signed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": {key: reviewer.get(key) for key in ["physician_id", "physician_name", "license_id", "department"]},
        "case_state_snapshot": case_state,
        "clinician_review_package": clinician_review_package or {},
        "final_diagnosis": final_diagnosis or {},
        "prescription": prescription or [],
        "administration": administration or {},
        "review_notes": review_notes or "",
        "warnings": warnings,
        "patient_release_gate": "physician_signed_only",
        "audit": {
            "model_generated_final_diagnosis": False,
            "model_generated_complete_prescription": False,
            "model_generated_patient_executable_dose": False,
            "physician_signed": True,
        },
    }
    return {"physician_review_record": record}
