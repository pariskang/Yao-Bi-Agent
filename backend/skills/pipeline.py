from __future__ import annotations

from typing import Any

from backend.engine.conformal import conformal_prediction_set
from backend.llm.dao_client import DaoClient
from backend.provenance import get_provenance
from backend.skills.safety_guard_skill import emergency_halt_required
from backend.skills.tao_report_generation_skill import tao_report_generation_skill
from backend.tools import get_registry


def run_case_pipeline(raw_text: str, use_llm: bool = False, dao_client: DaoClient | None = None) -> dict[str, Any]:
    # Every deterministic step goes through the tool registry: schema-validated input,
    # validated output, audit span. `call` raises the classified ToolError on failure,
    # which is correct for this in-process pipeline (there is no planner to re-plan).
    tools = get_registry()
    case_json = tools.call("case_extract_skill", raw_text=raw_text)
    normalized = tools.call("case_normalize_skill", case_json=case_json)

    # Red-flag gate BEFORE any TCM reasoning (global invariant, mirrored by the chat /
    # autonomous / orchestrator entry paths): confirmed emergency-category red flags
    # (cauda equina, progressive weakness, infection) hard-halt the clinical chain — no
    # syndrome, formula or herb output is produced, only the emergency referral report.
    # Contextual-urgent flags (e.g. fragility trauma) keep the case marked urgent while
    # the retrospective clinician-review analysis continues.
    gate_safety = tools.call("safety_guard_skill", case_json=case_json, matched_modules=None,
                             normalized_tags=normalized["normalized_tags"])
    if emergency_halt_required(gate_safety):
        return _halted_result(case_json, normalized, gate_safety, use_llm=use_llm, dao_client=dao_client)

    routed = tools.call("syndrome_router_skill", normalized_tags=normalized["normalized_tags"])
    formula = tools.call("formula_base_selector_skill", normalized_tags=normalized["normalized_tags"],
                         syndrome_candidates=routed["syndrome_candidates"])
    modules = tools.call("herb_module_composer_skill", normalized_tags=normalized["normalized_tags"],
                         formula_route=formula.get("primary_route"))
    conflicts = tools.call(
        "conflict_checker_skill",
        matched_modules=modules["matched_modules"], formula_route=formula.get("primary_route"),
        medications=case_json.get("medications") or [],
        conditions=(case_json.get("comorbidity_conditions") or []) + (case_json.get("western_diagnosis") or []),
    )
    # The primary formula route's core herbs join the safety scan: a route carrying
    # 附片/细辛 must surface a clinician-review caution even when no herb module matched.
    safety_pool = modules["matched_modules"] + ([formula["primary_route"]] if formula.get("primary_route") else [])
    safety = tools.call("safety_guard_skill", case_json=case_json, matched_modules=safety_pool,
                        normalized_tags=normalized["normalized_tags"])
    uncertainty = tools.call(
        "uncertainty_skill",
        syndrome_candidates=routed["syndrome_candidates"], normalized_tags=normalized["normalized_tags"],
        missing_fields=case_json.get("missing_fields"),
    )
    # Conformal differential: the project-calibrated set of syndromes the engine cannot
    # rule out under its own scoring (see backend/engine/conformal.py for caveats).
    try:
        uncertainty["uncertainty"]["conformal"] = conformal_prediction_set(routed["syndrome_candidates"])
    except (OSError, ValueError):
        # Missing/corrupt calibration file must never break the clinical pipeline.
        uncertainty["uncertainty"]["conformal"] = None
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
        "red_flag_gate": {
            "halted": False,
            "status": gate_safety.get("safety_status"),
            "confirmed_red_flags": [f.get("term") or f.get("id") for f in gate_safety.get("confirmed_red_flags") or []],
        },
        **uncertainty,
        "provenance": provenance,
        **report,
    }


def _halted_result(
    case_json: dict[str, Any],
    normalized: dict[str, Any],
    safety: dict[str, Any],
    *,
    use_llm: bool,
    dao_client: DaoClient | None,
) -> dict[str, Any]:
    """Emergency-halted pipeline output: same shape as the normal result, empty clinical chain.

    The deterministic report still renders (referral notice + red flags); the language
    model is deliberately not invoked — an emergency notice must not depend on a model.
    """

    provenance = get_provenance(getattr(dao_client, "config", None) if use_llm else None)
    report = tao_report_generation_skill(
        case_json=case_json,
        normalized_tags=normalized["normalized_tags"],
        syndrome_candidates=[],
        formula_route=None,
        matched_modules=[],
        conflicts=[],
        safety=safety,
        rule_hits=[],
        dao_client=None,
        use_llm=False,
        uncertainty=None,
        interaction_alerts=[],
        provenance=provenance,
    )
    return {
        "case_json": case_json,
        **normalized,
        "syndrome_candidates": [],
        "rule_hits": [],
        "formula_routes": [],
        "primary_route": None,
        "formula_rule_hits": [],
        "matched_modules": [],
        "conflicts": [],
        "interaction_alerts": [],
        "alert_summary": {"interruptive": 0, "advisory": 0, "requires_dual_signoff": False},
        "safety": safety,
        "red_flag_gate": {
            "halted": True,
            "status": safety.get("safety_status"),
            "reason": "确认急诊级红旗（马尾/进行性无力/感染类），中止辨证与方药推理，仅输出急诊转诊提示。",
            "confirmed_red_flags": [f.get("term") or f.get("id") for f in safety.get("confirmed_red_flags") or []],
        },
        "uncertainty": {
            "abstain": True,
            "assessment_note": "急诊红旗未排除，本例不进行证候与方药评估。",
            "conformal": None,
        },
        "provenance": provenance,
        **report,
    }
