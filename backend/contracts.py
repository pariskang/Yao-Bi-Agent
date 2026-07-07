"""Schema contracts for every cross-skill payload（全量输入输出契约层）.

Skills used to exchange loosely-shaped dicts: a missing field, a renamed key or a
type drift upstream silently corrupted downstream clinical reasoning. This module
pins the *minimum required shape* of each payload as an explicit, auditable
contract — zero dependencies (no pydantic), so the safety layer works everywhere
the rest of the stdlib-only stack works.

Design decisions:

* **Minimal-shape, extra-tolerant** — contracts assert required fields, types,
  enums and nested shapes; additional keys are always allowed so adding fields is
  never a breaking change. Removing/renaming/retyping one is.
* **Mode-aware enforcement** — ``YAOBI_CONTRACT_MODE``:
  - ``enforce``: violations raise :class:`ContractViolation` (the whole test suite
    runs in this mode via ``tests/conftest.py``, so drift fails CI);
  - ``warn`` (production default): violations are counted in the ops metrics and
    recorded in the audit log, but never crash a clinical request;
  - ``off``: validation skipped (perf escape hatch).
* **Const-pinning** — fields like the patient view's ``medication_advice`` are
  contractually pinned to ``null``: no upstream change can hand prescribing
  content to a patient without failing the contract.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

_MISSING = object()


class ContractViolation(TypeError):
    """A payload broke its declared cross-skill contract."""


@dataclass(frozen=True)
class Field:
    name: str
    types: tuple[type, ...] = (object,)
    required: bool = True
    nullable: bool = False
    enum: tuple[Any, ...] | None = None
    item_types: tuple[type, ...] | None = None
    item_contract: "Contract | None" = None
    contract: "Contract | None" = None
    # Pin the field to exactly this value (e.g. patient view medication_advice=None).
    const: Any = _MISSING


@dataclass(frozen=True)
class Contract:
    name: str
    fields: tuple[Field, ...]


def check(payload: Any, contract: Contract) -> list[str]:
    """Return human-readable violations of ``contract`` in ``payload`` (empty = valid)."""

    if not isinstance(payload, dict):
        return [f"{contract.name}: payload must be a dict, got {type(payload).__name__}"]
    violations: list[str] = []
    for field in contract.fields:
        value = payload.get(field.name, _MISSING)
        where = f"{contract.name}.{field.name}"
        if value is _MISSING:
            if field.required:
                violations.append(f"{where}: required field missing")
            continue
        if value is None:
            if not (field.nullable or field.const is None):
                violations.append(f"{where}: null not allowed")
            continue
        if field.const is not _MISSING and value != field.const:
            violations.append(f"{where}: must be exactly {field.const!r}, got {value!r}")
            continue
        if field.types != (object,) and not isinstance(value, field.types):
            violations.append(
                f"{where}: expected {'/'.join(t.__name__ for t in field.types)}, got {type(value).__name__}"
            )
            continue
        if field.enum is not None and value not in field.enum:
            violations.append(f"{where}: {value!r} not in {field.enum}")
            continue
        if isinstance(value, list):
            for i, item in enumerate(value):
                if field.item_types is not None and not isinstance(item, field.item_types):
                    violations.append(
                        f"{where}[{i}]: expected {'/'.join(t.__name__ for t in field.item_types)}, "
                        f"got {type(item).__name__}"
                    )
                    break
                if field.item_contract is not None:
                    nested = check(item, field.item_contract)
                    if nested:
                        violations.append(f"{where}[{i}]: {nested[0]}")
                        break
        elif field.contract is not None and isinstance(value, dict):
            nested = check(value, field.contract)
            if nested:
                violations.append(f"{where}: {nested[0]}")
    return violations


def contract_mode() -> str:
    mode = (os.getenv("YAOBI_CONTRACT_MODE") or "warn").strip().lower()
    return mode if mode in {"enforce", "warn", "off"} else "warn"


def validate(payload: Any, contract: Contract, source: str = "") -> Any:
    """Validate ``payload`` against ``contract`` per the active enforcement mode.

    Returns the payload unchanged so call sites can validate inline:
    ``return validate(result, SAFETY_ASSESSMENT, "safety_guard_skill")``.
    """

    mode = contract_mode()
    if mode == "off":
        return payload
    violations = check(payload, contract)
    if not violations:
        return payload
    detail = f"[{source or 'unknown'}] {contract.name} contract violated: " + "; ".join(violations[:5])
    if mode == "enforce":
        raise ContractViolation(detail)
    # warn: never break a clinical request — count + audit, then pass through.
    try:  # lazy import: contracts must stay dependency-free at import time
        from backend.audit import get_audit_log, get_counters

        get_counters().increment("contract_violation")
        get_counters().increment(f"contract_violation:{contract.name}")
        get_audit_log().record("contract_violation", {"contract": contract.name, "source": source, "detail": detail[:500]})
    except Exception:  # noqa: BLE001 — metrics failure must not mask the payload
        pass
    return payload


# ======================================================================== entities

CLINICAL_ENTITY = Contract("ClinicalEntity", (
    Field("entity", (str,)),
    Field("polarity", (str,), enum=("affirmed", "negated", "uncertain")),
    Field("temporality", (str,), enum=("current", "historical")),
    Field("experiencer", (str,)),
    Field("source_span", (str,)),
    Field("confidence", (int, float)),
))

# ==================================================================== case pipeline

CASE_FACTS = Contract("CaseFacts", (
    Field("age", (int, str)),
    Field("sex", (str,)),
    Field("main_complaint", (str,)),
    Field("duration", (str,)),
    Field("duration_class", (str,)),
    Field("symptoms", (list,), item_types=(str,)),
    Field("tongue", (list,), item_types=(str,)),
    Field("pulse", (list,), item_types=(str,)),
    Field("western_diagnosis", (list,), item_types=(str,)),
    Field("red_flags", (list,), item_types=(str,)),
    Field("red_flag_entities", (list,), item_contract=CLINICAL_ENTITY),
    Field("denied_red_flags", (list,), item_types=(str,)),
    Field("uncertain_red_flags", (list,), item_types=(str,)),
    Field("medications", (list,), item_types=(str,)),
    Field("comorbidity_conditions", (list,), item_types=(str,)),
    Field("missing_fields", (list,), item_types=(str,)),
    Field("evidence", (dict,)),
))

NORMALIZED_CASE = Contract("NormalizedCase", (
    Field("normalized_tags", (list,), item_types=(str,)),
    Field("tag_evidence", (dict,)),
))

SYNDROME_CANDIDATE = Contract("SyndromeCandidate", (
    Field("name", (str,)),
    Field("score", (int, float)),
    Field("confidence", (str,), required=False, enum=("high", "medium", "low")),
    Field("evidence_tags", (list,), item_types=(str,)),
    # Evidence chain fields exist on rule-engine candidates; interview-derived
    # candidates may omit them, so they are optional but type-pinned when present.
    Field("supporting_evidence", (list,), required=False, item_types=(str,)),
    Field("contradicting_evidence", (list,), required=False, item_types=(str,)),
    Field("missing_evidence", (list,), required=False, item_types=(str,)),
))

SYNDROME_RESULT = Contract("SyndromeResult", (
    Field("syndrome_candidates", (list,), item_contract=SYNDROME_CANDIDATE),
    Field("rule_hits", (list,), item_types=(dict,)),
))

FORMULA_ROUTE = Contract("FormulaRoute", (
    Field("name", (str,)),
    Field("score", (int, float)),
    Field("confidence", (str,), enum=("high", "medium", "low")),
    Field("core_module", (list,), required=False, item_types=(str,)),
    Field("non_prescriptive", (bool,), const=True),
))

FORMULA_RESULT = Contract("FormulaResult", (
    Field("formula_routes", (list,), item_contract=FORMULA_ROUTE),
    Field("primary_route", (dict,), nullable=True, contract=FORMULA_ROUTE),
    Field("formula_rule_hits", (list,), item_types=(dict,)),
))

HERB_MODULE = Contract("HerbModule", (
    Field("name", (str,)),
    Field("herbs", (list,), item_types=(str,)),
    Field("role", (str,)),
    Field("evidence_tags", (list,), item_types=(str,)),
    Field("non_prescriptive", (bool,), const=True),
))

HERB_RESULT = Contract("HerbResult", (
    Field("matched_modules", (list,), item_contract=HERB_MODULE),
))

SAFETY_ASSESSMENT = Contract("SafetyAssessment", (
    Field("safety_status", (str,), enum=("safe", "caution", "urgent")),
    Field("red_flags", (list,), item_types=(dict,)),
    Field("confirmed_red_flags", (list,), item_types=(dict,)),
    Field("denied_red_flags", (list,), item_types=(dict,)),
    Field("uncertain_red_flags", (list,), item_types=(dict,)),
    Field("need_further_inquiry", (list,), item_types=(str,)),
    Field("medication_risks", (list,), item_types=(str,)),
    Field("required_disclaimer", (bool,), const=True),
    Field("disclaimer", (str,), nullable=True),
))

UNCERTAINTY_BLOCK = Contract("UncertaintyBlock", (
    Field("abstain", (bool,)),
    Field("abstain_reason", (str,), nullable=True),
    Field("separation", (str,), enum=("none", "single", "narrow", "clear")),
    Field("assessment_note", (str,)),
    Field("differential_gaps", (list,), item_types=(dict,)),
    Field("non_final", (bool,), const=True),
))

# ===================================================================== agent layer

TOOL_OBSERVATION = Contract("ToolObservation", (
    Field("intent", (str,)),
    Field("label", (str,)),
    Field("answer", (str,)),
    Field("skills", (list,), item_types=(str,)),
    Field("evidence", (list,)),
    Field("used_llm", (bool,)),
))

ROUTING_DECISION = Contract("RoutingDecision", (
    Field("intent", (str,)),
    Field("method", (str,)),
    Field("confidence", (int, float)),
    Field("blocked", (bool,)),
    Field("guard", (dict,), required=False),
))

CRITIC_FINDING = Contract("CriticFinding", (
    Field("critic", (str,), enum=("safety", "evidence", "uncertainty", "completeness")),
    Field("severity", (str,), enum=("info", "warning", "veto")),
    Field("finding", (str,)),
    Field("recommendation", (str,), required=False),
))

AGENT_NEXT_ACTIONS = ("understand", "plan", "execute", "reflect", "ask_followup", "answer", "escalate", "abstain")

AGENT_STATE = Contract("AgentState", (
    Field("goal", (str,)),
    Field("round", (int,)),
    Field("max_rounds", (int,)),
    Field("known_facts", (list,), item_types=(str,)),
    Field("negated_facts", (list,), item_types=(str,)),
    Field("uncertain_facts", (list,), item_types=(str,)),
    Field("risk_state", (dict,), contract=SAFETY_ASSESSMENT),
    Field("candidate_decisions", (list,), item_contract=SYNDROME_CANDIDATE),
    Field("tool_plan", (list,), item_types=(dict,)),
    Field("executed_tools", (list,), item_types=(str,)),
    Field("observations", (list,), item_contract=TOOL_OBSERVATION),
    Field("critic_findings", (list,), item_contract=CRITIC_FINDING),
    Field("next_action", (str,), enum=AGENT_NEXT_ACTIONS),
    Field("transitions", (list,), item_types=(dict,)),
))

# ==================================================================== patient floor

PATIENT_VIEW = Contract("PatientView", (
    Field("role", (str,), const="patient"),
    Field("patient_visible_message", (str,)),
    Field("answer", (str,)),
    Field("forbidden_content_detected", (bool,)),
    Field("guard_violations", (list,), item_types=(str,)),
    Field("requires_doctor_review", (bool,), const=True),
    # Contractual null-pinning: prescribing content can never reach a patient view.
    Field("medication_advice", (object,), const=None, nullable=True),
    Field("clinician_draft", (object,), const=None, nullable=True),
    Field("answer_source", (str,), const="patient_safe_view"),
))

GUARD_VERDICT = Contract("GuardVerdict", (
    Field("allowed", (bool,)),
    Field("violations", (list,), item_types=(dict,)),
))

# Blackboard key → contract (multi-agent shared working memory shapes).
BLACKBOARD_CONTRACTS: dict[str, Contract] = {
    "routed": SYNDROME_RESULT,
    "formula": FORMULA_RESULT,
    "modules": HERB_RESULT,
    "safety": SAFETY_ASSESSMENT,
}
