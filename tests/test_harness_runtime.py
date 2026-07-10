"""Tests for the v0.9 harness governance layer.

Covers: unified run lifecycle (status machine, budget, stop reasons), the runtime
tool registry (RBAC, schema validation, error taxonomy, envelope), blackboard field
ownership, two-phase override approvals, hash-chained audit, independent critics,
claim-modality overstatement detection, and expanded provenance.
"""

from __future__ import annotations

import pytest

from backend.agents.autonomous_agent import AutonomousQAAgent
from backend.agents.base import Blackboard, BlackboardOwnershipError
from backend.agents.critics import contradiction_critic, evidence_critic, policy_critic
from backend.agents.orchestrator import AgentOrchestrator
from backend.audit.audit_log import AuditLog, verify_chain
from backend.provenance import get_provenance
from backend.runtime.approvals import ApprovalManager
from backend.runtime.run_context import AgentRun, IllegalRunTransition, RunBudget, RunStatus, StopReason
from backend.skills.groundedness_skill import check_groundedness
from backend.tools import get_registry


# -- run lifecycle -----------------------------------------------------------------------

def test_run_status_machine_rejects_illegal_transitions():
    run = AgentRun(goal="test")
    run.start()
    run.finish(StopReason.GOAL_COMPLETED)
    assert run.status is RunStatus.COMPLETED and run.terminal
    with pytest.raises(IllegalRunTransition):
        run.transition(RunStatus.RUNNING)


def test_run_budget_reports_exhaustion_reason():
    budget = RunBudget(max_iterations=1)
    assert budget.charge("iteration") is None
    assert budget.charge("iteration") is StopReason.BUDGET_EXHAUSTED


def test_autonomous_turn_carries_run_block_with_stop_reason():
    agent = AutonomousQAAgent(case_state={"normalized_tags": ["dark_tongue", "chronic_yabi"]})
    turn = agent.run("这个病人是什么证型、用什么方？")
    run = turn["run"]
    assert run["status"] == "COMPLETED"
    assert run["stop_reason"] in {"goal_completed", "insufficient_evidence"}
    assert "/" in run["budget"]["iterations"]


def test_autonomous_red_flag_gate_yields_safety_halted_run():
    agent = AutonomousQAAgent(case_state={"normalized_tags": [], "red_flags": {"status": "urgent", "positive_items": ["尿潴留"]}})
    turn = agent.run("是什么证型？")
    assert turn["run"]["status"] == "SAFETY_HALTED"
    assert turn["run"]["stop_reason"] == "safety_halt"


def test_orchestrator_run_block_reflects_halt():
    halted = AgentOrchestrator().run({"normalized_tags": [], "red_flags": {"status": "urgent", "positive_items": ["会阴麻木"]}})
    assert halted["run"]["status"] == "SAFETY_HALTED"
    normal = AgentOrchestrator().run({"normalized_tags": ["dark_tongue", "chronic_yabi"], "red_flags": {"status": "safe"}})
    assert normal["run"]["status"] == "COMPLETED"


# -- tool registry -----------------------------------------------------------------------

def test_registry_success_envelope_and_span_fields():
    res = get_registry().invoke("syndrome_router_skill", {"normalized_tags": ["dark_tongue", "chronic_yabi"]}, role="clinician")
    assert res["status"] == "success"
    assert res["output"]["syndrome_candidates"]
    assert res["span_id"].startswith("span-") and res["duration_ms"] >= 0


def test_registry_denies_unauthorized_role():
    res = get_registry().invoke("physician_review_skill", {"case_state": {}, "reviewer": {}}, role="patient")
    assert res["status"] == "error" and res["error_type"] == "tool_policy_denied"
    # high-risk physician record tool: even "system" may not call it
    res = get_registry().invoke("physician_review_skill", {"case_state": {}, "reviewer": {}}, role="system")
    assert res["error_type"] == "tool_policy_denied"


def test_registry_validates_input_schema():
    res = get_registry().invoke("case_extract_skill", {"raw_text": 42}, role="patient")
    assert res["error_type"] == "tool_input_error"
    res = get_registry().invoke("case_extract_skill", {}, role="patient")
    assert res["error_type"] == "tool_input_error"


def test_registry_unknown_tool_and_runtime_bound_tool():
    assert get_registry().invoke("no_such_tool", {})["error_type"] == "tool_not_found"
    res = get_registry().invoke("tao_report_generation_skill", {}, role="clinician")
    assert res["error_type"] == "tool_policy_denied"  # runtime-bound: host component only


def test_registry_call_raises_classified_errors():
    from backend.tools import ToolInputError

    with pytest.raises(ToolInputError):
        get_registry().call("syndrome_router_skill", role="clinician", normalized_tags="oops")


# -- blackboard ownership ------------------------------------------------------------------

def test_blackboard_enforces_key_ownership():
    bb = Blackboard(case_state={})
    bb.put("routed", {"x": 1}, producer="TcmSyndromeAgent")
    assert bb.meta["routed"]["producer"] == "TcmSyndromeAgent"
    with pytest.raises(BlackboardOwnershipError):
        bb.put("routed", {"x": 2}, producer="HerbModuleAgent")
    bb.put("scratch", 1, producer="AnyAgent")  # unowned keys stay open


# -- approvals ------------------------------------------------------------------------------

def test_approval_two_phase_and_reviewer_binding():
    manager = ApprovalManager()
    req = manager.create(action_type="override_emergency_referral", session_id="s1",
                         reviewer_id="dr-1", reason="测试", payload={"red_flags": ["会阴麻木"]})
    assert req.status == "pending" and req.risk_level == "critical"
    assert manager.decide(req.approval_id, decision="approve", reviewer_id="dr-2") is None
    decided = manager.decide(req.approval_id, decision="approve", reviewer_id="dr-1")
    assert decided is not None and decided.status == "approved"
    # already decided → cannot re-decide
    assert manager.decide(req.approval_id, decision="approve", reviewer_id="dr-1") is None


# -- hash-chained audit ---------------------------------------------------------------------

def test_audit_chain_verifies_and_detects_tampering(tmp_path):
    log = AuditLog(directory=tmp_path, enabled=True)
    records = [log.record("e1", {"a": 1}), log.record("e2", {"b": 2}), log.record("e3", {"c": 3})]
    assert all(records)
    assert verify_chain(records)["valid"] is True
    records[1]["b"] = 999  # tamper
    result = verify_chain(records)
    assert result["valid"] is False and result["first_break_seq"] == records[1]["seq"]


# -- independent critics ----------------------------------------------------------------------

def test_contradiction_critic_flags_cold_and_heat_together():
    findings = contradiction_critic(["cold_aversion", "burning_pain", "dark_tongue"])
    assert findings and findings[0]["axis"] == "寒象与热象并见"
    assert contradiction_critic(["cold_aversion", "dark_tongue"]) == []


def test_policy_and_evidence_critics_are_narrow():
    steps = [{"intent": "syndrome_inquiry", "skills": ["syndrome_router_skill"], "evidence": []}]
    assert policy_critic("patient", steps)["violations"] == ["syndrome_inquiry"]
    assert policy_critic("clinician", steps)["ok"] is True
    assert evidence_critic(steps)["ungrounded_steps"] == ["syndrome_inquiry"]


def test_autonomous_critique_includes_contradictions():
    agent = AutonomousQAAgent(case_state={"normalized_tags": ["cold_aversion", "burning_pain", "dark_tongue", "chronic_yabi"]})
    turn = agent.run("这个病人是什么证型？")
    assert turn["critique"]["contradictions"]
    assert "反证批判者" in turn["answer"]


# -- claim modality (overstatement) -----------------------------------------------------------

def test_groundedness_flags_overstated_certainty():
    evidence = {"syndrome_candidates": [{"name": "肾阳不足证"}], "formula_routes": []}
    result = check_groundedness("患者确定为肾阳不足证，毫无疑问。", evidence)
    assert result["overstatements"]
    assert "断言强度" in result["annotation"]
    hedged = check_groundedness("本案倾向肾阳不足证，供医师审定。", evidence)
    assert hedged["overstatements"] == []


# -- provenance --------------------------------------------------------------------------------

def test_provenance_carries_runtime_fingerprints():
    block = get_provenance()
    for key in ("prompt_bundle_hash", "guard_version", "policy_bundle_hash", "tool_registry_hash", "case_schema_hash"):
        assert block.get(key), f"missing {key}"
    assert "git_commit" in block
