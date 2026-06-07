from __future__ import annotations

from typing import Any


def clinician_review_package_skill(
    case_state: dict[str, Any],
    syndrome_candidates: list[dict[str, Any]] | None = None,
    formula_routes: list[dict[str, Any]] | None = None,
    matched_modules: list[dict[str, Any]] | None = None,
    safety: dict[str, Any] | None = None,
    requested_outputs: list[str] | None = None,
) -> dict[str, Any]:
    """Build a clinician-review package without issuing a diagnosis or prescription.

    This is the safe response surface for requests like "给出诊断和处方": it
    returns differential diagnoses, TCM pattern hypotheses, formula-route signals,
    and historical experience modules, all explicitly marked as non-prescriptive
    and requiring clinician review.
    """
    tags = set(case_state.get("normalized_tags") or [])
    neuro = case_state.get("neuro_ortho", {})
    comorbidity = case_state.get("comorbidity", {})
    differentials = []
    if tags & {"radiating_leg_pain", "lower_limb_numbness"} or neuro.get("numbness") not in [None, "没有"]:
        differentials.append({
            "name": "腰椎间盘突出/神经根受压可能",
            "basis": "下肢麻木或放射痛线索",
            "status": "待医生结合查体和影像复核",
        })
    if neuro.get("walking_limitation") == "是":
        differentials.append({
            "name": "腰椎管狭窄可能",
            "basis": "行走后腰腿痛或麻木加重，休息/弯腰缓解线索",
            "status": "待医生结合查体和影像复核",
        })
    diseases = set(comorbidity.get("diseases") or []) | set(neuro.get("western_diagnosis") or [])
    if "骨质疏松" in diseases or "osteoporosis" in tags:
        differentials.append({
            "name": "骨质疏松相关腰背痛/压缩骨折风险",
            "basis": "骨质疏松或骨密度信息线索",
            "status": "若急性剧痛或外伤后发作，需优先线下评估",
        })
    if not differentials:
        differentials.append({
            "name": "非特异性腰痛/腰肌劳损等需鉴别",
            "basis": "现有信息不足以形成稳定方向",
            "status": "待医生面诊复核",
        })

    tcm_hypotheses = [
        {
            "pattern": item.get("name"),
            "score": item.get("score"),
            "evidence_tags": item.get("evidence_tags", []),
            "status": "候选证型，待医生复核",
        }
        for item in (syndrome_candidates or [])
    ]
    formula_hypotheses = [
        {
            "route": item.get("name"),
            "score": item.get("score"),
            "evidence_tags": item.get("evidence_tags", []),
            "status": "方剂路线信号，非处方",
        }
        for item in (formula_routes or [])
    ]
    module_experience = [
        {
            "module": item.get("name"),
            "representative_herbs": item.get("herbs", []),
            "evidence_tags": item.get("evidence_tags", []),
            "status": "历史经验模块解释，非患者自用方案",
        }
        for item in (matched_modules or [])
    ]
    requested = set(requested_outputs or [])
    forbidden_requested = sorted(requested & {
        "final_diagnosis",
        "complete_prescription",
        "patient_executable_dose",
        "self_medication_plan",
        "服用剂量",
        "最终诊断",
        "完整处方",
        "患者可执行剂量",
    })
    package = {
        "request_guard": {
            "forbidden_requested": forbidden_requested,
            "blocked": bool(forbidden_requested),
            "message": (
                "已拦截最终诊断、完整处方或患者可执行剂量请求；系统仅提供待医生复核的鉴别方向、候选证型、方剂路线信号和经验模块。"
                if forbidden_requested
                else "未请求患者可执行诊疗输出；继续提供医生复核型分析。"
            ),
            "safe_alternatives": [
                "标准化医案",
                "西医鉴别方向（待医生复核）",
                "中医候选证型（待医生复核）",
                "方剂路线信号（非处方）",
                "药物模块经验解释（无自服剂量）",
                "安全风险与信息缺口",
            ],
        },
        "diagnosis_review": {
            "western_differentials": differentials,
            "tcm_pattern_hypotheses": tcm_hypotheses,
            "non_final_diagnosis": True,
        },
        "prescription_review": {
            "formula_route_hypotheses": formula_hypotheses,
            "module_experience": module_experience,
            "complete_prescription_generated": False,
            "patient_executable_dose_generated": False,
            "non_prescriptive": True,
        },
        "safety_boundary": {
            "status": (safety or {}).get("safety_status", "unknown"),
            "message": "本节回应诊断/处方需求时，仅提供待医生复核的鉴别方向、证型假设、方剂路线信号和经验模块；不构成最终诊断、临床处方或患者自服方案。",
        },
    }
    return {"clinician_review_package": package}
