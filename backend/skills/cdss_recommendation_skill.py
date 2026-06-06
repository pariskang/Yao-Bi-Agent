from __future__ import annotations

from typing import Any

HIGH_RISK_HERBS = {"附片", "细辛", "蜈蚣", "全蝎", "制川乌", "制草乌", "乌头"}


def cdss_recommendation_skill(
    case_state: dict[str, Any],
    syndrome_candidates: list[dict[str, Any]] | None = None,
    formula_routes: list[dict[str, Any]] | None = None,
    matched_modules: list[dict[str, Any]] | None = None,
    safety: dict[str, Any] | None = None,
    user_role: str = "clinician",
) -> dict[str, Any]:
    """Generate a clinician-facing CDSS draft, not a final order.

    The model/rule layer may automatically assemble diagnostic *candidates* and
    prescription *strategy drafts* for a clinical decision support workflow. It
    must not create final signed diagnoses, medication orders, administration
    instructions, or patient-executable doses. Those are reserved for
    ``physician_review_skill``.
    """
    if user_role not in {"clinician", "licensed_physician", "researcher"}:
        return {
            "cdss_recommendation": {
                "status": "blocked_patient_role",
                "message": "CDSS草案仅供医生/研究者界面使用，患者端只显示标准医案和医生复核清单。",
                "patient_visible": False,
            }
        }

    tags = set(case_state.get("normalized_tags") or [])
    neuro = case_state.get("neuro_ortho", {})
    comorbidity = case_state.get("comorbidity", {})
    western_candidates = []
    if tags & {"radiating_leg_pain", "lower_limb_numbness"} or neuro.get("numbness") not in [None, "没有"]:
        western_candidates.append({
            "candidate": "腰椎间盘突出/神经根受压相关腰腿痛",
            "supporting_evidence": ["下肢麻木", "放射痛或远端下肢受累线索"],
            "review_required": ["直腿抬高试验/神经系统查体", "腰椎MRI或CT", "肌力、感觉、反射评估"],
            "status": "CDSS候选诊断，未签名非最终诊断",
        })
    if neuro.get("walking_limitation") == "是":
        western_candidates.append({
            "candidate": "腰椎管狭窄相关间歇性跛行可能",
            "supporting_evidence": ["行走后加重、休息或弯腰缓解线索"],
            "review_required": ["影像学椎管评估", "下肢血管性跛行鉴别"],
            "status": "CDSS候选诊断，未签名非最终诊断",
        })
    diseases = set(comorbidity.get("diseases") or []) | set(neuro.get("western_diagnosis") or [])
    if "骨质疏松" in diseases or "osteoporosis" in tags:
        western_candidates.append({
            "candidate": "骨质疏松相关腰背痛/压缩骨折风险",
            "supporting_evidence": ["骨质疏松或骨密度检查线索"],
            "review_required": ["骨密度报告", "必要时胸腰椎影像排除压缩骨折"],
            "status": "CDSS鉴别方向，需医生排除急性骨折风险",
        })
    if not western_candidates:
        western_candidates.append({
            "candidate": "非特异性腰痛/腰肌劳损等待鉴别",
            "supporting_evidence": ["现有信息不足"],
            "review_required": ["面诊查体", "必要时影像与实验室检查"],
            "status": "CDSS鉴别方向，未签名非最终诊断",
        })

    tcm_candidates = [
        {
            "candidate": item.get("name"),
            "score": item.get("score"),
            "evidence_tags": item.get("evidence_tags", []),
            "status": "CDSS候选证型，待中医师复核",
        }
        for item in (syndrome_candidates or [])
    ]

    formula_strategy = []
    for route in formula_routes or []:
        formula_strategy.append({
            "route": route.get("name"),
            "score": route.get("score"),
            "core_module": route.get("core_module", []),
            "evidence_tags": route.get("evidence_tags", []),
            "status": "CDSS方剂路线草案，非最终处方",
        })

    module_strategy = []
    high_risk_hits = set()
    for module in matched_modules or []:
        herbs = module.get("herbs", [])
        high_risk_hits.update(set(herbs) & HIGH_RISK_HERBS)
        module_strategy.append({
            "module": module.get("name"),
            "representative_herbs": herbs,
            "evidence_tags": module.get("evidence_tags", []),
            "role": module.get("role"),
            "status": "CDSS药物模块草案，需医师取舍、配伍、剂量和禁忌审核",
        })

    return {
        "cdss_recommendation": {
            "status": "draft_for_clinician_review",
            "automation_level": "model_rule_generated_draft_not_signed_order",
            "patient_visible": False,
            "western_diagnosis_candidates": western_candidates,
            "tcm_syndrome_candidates": tcm_candidates,
            "prescription_strategy_draft": {
                "formula_routes": formula_strategy,
                "herb_modules": module_strategy,
                "complete_prescription_generated": False,
                "patient_executable_dose_generated": False,
                "dose_policy": "剂量、煎服法、疗程必须由医师在physician_review_skill中手工录入并签名。",
            },
            "safety": {
                "safety_status": (safety or {}).get("safety_status", "unknown"),
                "high_risk_herbs_in_modules": sorted(high_risk_hits),
                "required_review": [
                    "红旗症状与急症排除",
                    "影像/查体/既往用药复核",
                    "高风险药物与合并病禁忌复核",
                    "医师手工签名后方可形成最终诊断和处方",
                ],
            },
        }
    }
