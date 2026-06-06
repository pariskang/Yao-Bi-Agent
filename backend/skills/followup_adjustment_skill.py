from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.engine.rule_engine import RULES_DIR, load_yaml


def followup_adjustment_skill(followup_tags: list[str]) -> dict[str, Any]:
    config = load_yaml(Path(RULES_DIR) / "08_followup_rules.yaml") or {}
    tag_set = set(followup_tags)
    hits = []
    for rule in config.get("followup_rules", []):
        if tag_set & set(rule.get("trigger") or []):
            hits.append({"id": rule["id"], "action": rule.get("action", {}), "meaning": rule.get("meaning", "")})
    stage = "巩固期" if "pain_reduced" in tag_set else "观察期"
    return {"followup_stage": stage, "rule_hits": hits, "non_prescriptive": True}
