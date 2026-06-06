from __future__ import annotations

from typing import Any

from backend.llm.dao_client import DaoClient
from backend.skills.case_extract_skill import case_extract_skill
from backend.skills.case_normalize_skill import case_normalize_skill
from backend.skills.conflict_checker_skill import conflict_checker_skill
from backend.skills.formula_base_selector_skill import formula_base_selector_skill
from backend.skills.herb_module_composer_skill import herb_module_composer_skill
from backend.skills.safety_guard_skill import safety_guard_skill
from backend.skills.syndrome_router_skill import syndrome_router_skill
from backend.skills.tao_report_generation_skill import tao_report_generation_skill


def run_case_pipeline(raw_text: str, use_llm: bool = False, dao_client: DaoClient | None = None) -> dict[str, Any]:
    case_json = case_extract_skill(raw_text)
    normalized = case_normalize_skill(case_json)
    routed = syndrome_router_skill(normalized["normalized_tags"])
    formula = formula_base_selector_skill(normalized["normalized_tags"], routed["syndrome_candidates"])
    modules = herb_module_composer_skill(normalized["normalized_tags"], formula.get("primary_route"))
    conflicts = conflict_checker_skill(modules["matched_modules"], formula.get("primary_route"))
    safety = safety_guard_skill(case_json, modules["matched_modules"], normalized["normalized_tags"])
    report = tao_report_generation_skill(
        case_json=case_json,
        normalized_tags=normalized["normalized_tags"],
        syndrome_candidates=routed["syndrome_candidates"],
        formula_route=formula.get("primary_route"),
        matched_modules=modules["matched_modules"],
        conflicts=conflicts["conflicts"],
        safety=safety,
        rule_hits=routed["rule_hits"] + formula["formula_rule_hits"],
        dao_client=dao_client,
        use_llm=use_llm,
    )
    return {
        "case_json": case_json,
        **normalized,
        **routed,
        **formula,
        **modules,
        **conflicts,
        "safety": safety,
        **report,
    }
