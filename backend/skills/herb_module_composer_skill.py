from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.engine.rule_engine import RULES_DIR, load_yaml


def herb_module_composer_skill(normalized_tags: list[str], formula_route: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_yaml(Path(RULES_DIR) / "04_module_rules.yaml") or {}
    tag_set = set(normalized_tags)
    matched = []
    for module_id, module in (config.get("modules") or {}).items():
        triggers = set(module.get("triggers") or [])
        evidence = sorted(tag_set & triggers)
        if evidence:
            matched.append({
                "id": module_id,
                "name": module["name"],
                "score": len(evidence) * 2 + (2 if module.get("role") == "base" else 0),
                "evidence_tags": evidence,
                "role": module.get("role", "add_on"),
                "herbs": module.get("herbs", []),
                "note": module.get("note", ""),
                "non_prescriptive": True,
            })
    return {"matched_modules": sorted(matched, key=lambda item: item["score"], reverse=True)}
