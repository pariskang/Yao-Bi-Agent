from __future__ import annotations

from typing import Any

from backend.engine.conflict_resolver import check_conflicts


def conflict_checker_skill(matched_modules: list[dict[str, Any]], formula_route: dict[str, Any] | None = None) -> dict[str, Any]:
    items = list(matched_modules)
    if formula_route:
        items.append({"effect": {"core_module": formula_route.get("core_module", [])}})
    return {"conflicts": check_conflicts(items)}
