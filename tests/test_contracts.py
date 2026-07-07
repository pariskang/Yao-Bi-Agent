"""Contract-layer tests: the validator itself, enforcement modes, and const-pinning."""

from __future__ import annotations

import pytest

from backend.contracts import (
    AGENT_STATE,
    CASE_FACTS,
    CLINICAL_ENTITY,
    PATIENT_VIEW,
    SAFETY_ASSESSMENT,
    SYNDROME_CANDIDATE,
    TOOL_OBSERVATION,
    Contract,
    ContractViolation,
    Field,
    check,
    validate,
)

_ENTITY = {
    "entity": "发热", "polarity": "negated", "temporality": "current",
    "experiencer": "patient", "source_span": "无发热寒战", "confidence": 0.95,
}


def test_valid_entity_passes():
    assert check(_ENTITY, CLINICAL_ENTITY) == []


def test_missing_required_field_is_reported():
    bad = dict(_ENTITY)
    del bad["polarity"]
    violations = check(bad, CLINICAL_ENTITY)
    assert any("polarity" in v and "missing" in v for v in violations)


def test_enum_violation_is_reported():
    bad = {**_ENTITY, "polarity": "maybe"}
    assert any("not in" in v for v in check(bad, CLINICAL_ENTITY))


def test_type_violation_is_reported():
    bad = {**_ENTITY, "confidence": "high"}
    assert any("confidence" in v for v in check(bad, CLINICAL_ENTITY))


def test_extra_fields_are_always_allowed():
    assert check({**_ENTITY, "extra_key": 123}, CLINICAL_ENTITY) == []


def test_nested_item_contract_is_checked():
    contract = Contract("Wrap", (Field("items", (list,), item_contract=CLINICAL_ENTITY),))
    assert check({"items": [_ENTITY]}, contract) == []
    assert check({"items": [{"entity": "x"}]}, contract)


def test_const_pinning_blocks_prescribing_content_in_patient_view():
    view = {
        "role": "patient", "patient_visible_message": "x", "answer": "x",
        "forbidden_content_detected": False, "guard_violations": [],
        "requires_doctor_review": True, "medication_advice": None,
        "clinician_draft": None, "answer_source": "patient_safe_view",
    }
    assert check(view, PATIENT_VIEW) == []
    leaked = {**view, "medication_advice": "细辛3g"}
    assert any("medication_advice" in v for v in check(leaked, PATIENT_VIEW))


def test_enforce_mode_raises(monkeypatch):
    monkeypatch.setenv("YAOBI_CONTRACT_MODE", "enforce")
    with pytest.raises(ContractViolation):
        validate({"entity": "x"}, CLINICAL_ENTITY, "test")


def test_warn_mode_counts_and_passes_through(monkeypatch):
    monkeypatch.setenv("YAOBI_CONTRACT_MODE", "warn")
    from backend.audit import get_counters

    before = get_counters().snapshot().get("contract_violation", 0)
    payload = {"entity": "x"}
    assert validate(payload, CLINICAL_ENTITY, "test") is payload
    assert get_counters().snapshot().get("contract_violation", 0) == before + 1


def test_off_mode_skips(monkeypatch):
    monkeypatch.setenv("YAOBI_CONTRACT_MODE", "off")
    payload = {"entity": "x"}
    assert validate(payload, CLINICAL_ENTITY, "test") is payload


# ------------------------------------------------- real producers conform end-to-end

def test_extractor_output_conforms():
    from backend.skills.case_extract_skill import case_extract_skill

    out = case_extract_skill("患者女，68岁，腰痛反复5年，否认外伤，无发热寒战，舌暗苔白腻。")
    assert check(out, CASE_FACTS) == []


def test_safety_output_conforms():
    from backend.skills.pipeline import run_case_pipeline

    result = run_case_pipeline("患者男，45岁，腰痛伴会阴麻木，尿不出来。")
    assert check(result["safety"], SAFETY_ASSESSMENT) == []
    for candidate in result["syndrome_candidates"]:
        assert check(candidate, SYNDROME_CANDIDATE) == []


def test_tool_observation_conforms():
    from backend.agents.conversation import ConversationSession

    obs = ConversationSession(case_state={"normalized_tags": ["dark_tongue", "chronic_yabi"]}).invoke("syndrome_inquiry")
    assert check(obs, TOOL_OBSERVATION) == []


def test_agent_state_contract_shape():
    from backend.skills.safety_guard_skill import safety_guard_skill

    state = {
        "goal": "判断证型", "round": 1, "max_rounds": 3,
        "known_facts": ["dark_tongue"], "negated_facts": ["发热"], "uncertain_facts": [],
        "risk_state": safety_guard_skill({"evidence": {"raw_text": ""}}),
        "candidate_decisions": [], "tool_plan": [], "executed_tools": [],
        "observations": [], "critic_findings": [], "next_action": "plan", "transitions": [],
    }
    assert check(state, AGENT_STATE) == []
