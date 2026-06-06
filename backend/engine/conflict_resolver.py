from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.engine.rule_engine import RULES_DIR, load_yaml


def flatten_herbs(items: list[dict[str, Any]]) -> set[str]:
    herbs: set[str] = set()
    for item in items:
        herbs.update(item.get("herbs") or [])
        effect = item.get("effect") or {}
        herbs.update(effect.get("core_module") or [])
    return herbs


def check_conflicts(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    config = load_yaml(Path(RULES_DIR) / "06_conflict_rules.yaml") or {}
    herbs = flatten_herbs(items)
    conflicts = []
    for rule in config.get("conflicts", []):
        group_a = set(rule.get("group_a") or [])
        group_b = set(rule.get("group_b") or [])
        if herbs & group_a and herbs & group_b:
            conflicts.append({
                "id": rule["id"],
                "type": "route_conflict",
                "description": rule["meaning"],
                "resolution": rule.get("action", "require_clinician_review"),
            })
    return conflicts
