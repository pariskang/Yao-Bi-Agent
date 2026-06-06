from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.engine.rule_engine import RULES_DIR, load_yaml


def dose_grammar_explainer_skill(herbs: list[str]) -> dict[str, Any]:
    config = load_yaml(Path(RULES_DIR) / "05_dose_rules.yaml") or {}
    dose_rules = config.get("dose_rules") or {}
    interpretations = []
    for herb in herbs:
        if herb in dose_rules:
            rule = dose_rules[herb]
            interpretations.append({
                "herb": herb,
                "experience_dose": f"沈老经验中可见：{rule.get('common')}",
                "rule_meaning": rule.get("meaning"),
                "warning": rule.get("warning"),
                "safety_level": "requires_clinician_review",
                "non_prescriptive": True,
            })
    return {"dose_interpretation": interpretations}
