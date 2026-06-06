from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.engine.rule_engine import RULES_DIR, load_yaml

TAG_REDFLAG_MAP = {
    "trauma_fracture_risk": "trauma_fracture_risk",
    "cauda_equina_symptoms": "cauda_equina_symptoms",
    "progressive_weakness": "progressive_weakness",
    "fever_or_infection": "fever_or_infection",
    "cancer_history": "cancer_history",
    "unexplained_weight_loss": "unexplained_weight_loss",
    "anticoagulant_use": "anticoagulant_use",
}


def safety_guard_skill(case_json: dict[str, Any], matched_modules: list[dict[str, Any]] | None = None, normalized_tags: list[str] | None = None) -> dict[str, Any]:
    config = load_yaml(Path(RULES_DIR) / "07_safety_rules.yaml") or {}
    text = (case_json.get("evidence") or {}).get("raw_text", "")
    tags = set(normalized_tags or [])
    red_flags = []
    for key, message in (config.get("red_flags") or {}).items():
        if key in tags:
            red_flags.append({"id": key, "message": message})
    for raw in case_json.get("red_flags") or []:
        red_flags.append({"id": "raw_red_flag", "message": f"原文红旗线索：{raw}"})
    if "自服" in text or "自己买药" in text or "开方" in text:
        red_flags.append({"id": "self_medication_request", "message": config["red_flags"]["self_medication_request"]})
    high_risk = set(config.get("toxic_or_high_risk_herbs") or [])
    medication_risks = []
    for module in matched_modules or []:
        risky = sorted(high_risk & set(module.get("herbs") or []))
        if risky:
            medication_risks.append(f"{', '.join(risky)} 属于需严格医生审核的高风险/特殊药物，不可自行使用。")
    status = "urgent" if any(flag["id"] in {"cauda_equina_symptoms", "progressive_weakness", "raw_red_flag"} for flag in red_flags) else "caution" if red_flags or medication_risks else "safe"
    return {
        "safety_status": status,
        "red_flags": red_flags,
        "medication_risks": sorted(set(medication_risks)),
        "required_disclaimer": True,
        "disclaimer": config.get("required_disclaimer"),
    }
