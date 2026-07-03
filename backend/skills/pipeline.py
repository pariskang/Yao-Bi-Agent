from __future__ import annotations

from typing import Any

from backend.llm.dao_client import DaoClient
from backend.provenance import get_provenance
from backend.skills.case_extract_skill import case_extract_skill
from backend.skills.case_normalize_skill import case_normalize_skill
from backend.skills.conflict_checker_skill import conflict_checker_skill
from backend.skills.formula_base_selector_skill import formula_base_selector_skill
from backend.skills.herb_module_composer_skill import herb_module_composer_skill
from backend.skills.safety_guard_skill import safety_guard_skill
from backend.skills.syndrome_router_skill import syndrome_router_skill
from backend.skills.tao_report_generation_skill import tao_report_generation_skill
from backend.skills.uncertainty_skill import uncertainty_skill


def run_case_pipeline(raw_text: str, use_llm: bool = False, dao_client: DaoClient | None = None) -> dict[str, Any]:
    case_json = case_extract_skill(raw_text)
    normalized = case_normalize_skill(case_json)
    routed = syndrome_router_skill(normalized["normalized_tags"])
    formula = formula_base_selector_skill(normalized["normalized_tags"], routed["syndrome_candidates"])
    modules = herb_module_composer_skill(normalized["normalized_tags"], formula.get("primary_route"))
    conflicts = conflict_checker_skill(
        modules["matched_modules"], formula.get("primary_route"),
        medications=case_json.get("medications") or [],
        conditions=(case_json.get("comorbidity_conditions") or []) + (case_json.get("western_diagnosis") or []),
    )
    safety = safety_guard_skill(case_json, modules["matched_modules"], normalized["normalized_tags"])
    uncertainty = uncertainty_skill(
        routed["syndrome_candidates"], normalized["normalized_tags"], case_json.get("missing_fields"),
    )
    provenance = get_provenance(getattr(dao_client, "config", None) if use_llm else None)
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
        uncertainty=uncertainty["uncertainty"],
        interaction_alerts=conflicts.get("interaction_alerts"),
        provenance=provenance,
    )
    return {
        "case_json": case_json,
        **normalized,
        **routed,
        **formula,
        **modules,
        **conflicts,
        "safety": safety,
        **uncertainty,
        "provenance": provenance,
        **report,
    }
