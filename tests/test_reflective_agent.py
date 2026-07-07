"""Multi-round reflective state machine tests: loop, critics, veto, followup, contracts."""

from __future__ import annotations

import importlib

from backend.agents.reflective_agent import ReflectiveClinicalAgent
from backend.contracts import AGENT_STATE, check


def _server(monkeypatch, backend: str = "mock"):
    monkeypatch.setenv("TAO_BACKEND", backend)
    monkeypatch.setenv("YAOBI_ALLOW_UNAUTH_CLINICIAN_DEMO", "1")
    import backend.server as server_module

    return importlib.reload(server_module)


def _case(tags: list[str], red_flags: dict | None = None) -> dict:
    return {"normalized_tags": tags, "red_flags": red_flags or {"status": "safe", "positive_items": []}}


# ------------------------------------------------------------------ terminal: answer

def test_clear_case_answers_with_critic_trace():
    agent = ReflectiveClinicalAgent(case_state=_case(["dark_tongue", "chronic_yabi", "lumbar_leg_pain", "white_greasy_coating"]))
    turn = agent.run("这个病人是什么证型？")
    assert turn["next_action"] == "answer"
    assert turn["candidate_decisions"][0]["name"] == "气血痹阻证"
    assert turn["critic_findings"], "critics must leave an audit trail"
    assert turn["transitions"][0]["to"] == "plan"
    assert turn["transitions"][-1]["to"] == "answer"
    assert check(turn["agent_state"], AGENT_STATE) == []


# --------------------------------------------------------------- multi-round replan

def test_narrow_separation_triggers_second_round():
    # 寒湿痹阻(5分) vs 气血痹阻(4分) — a 1-point margin is "narrow", so the uncertainty
    # critic queues an evidence round and the loop genuinely replans.
    agent = ReflectiveClinicalAgent(case_state=_case(["lumbar_leg_pain", "chronic_yabi", "cold_aggravation", "heavy_lower_limb", "white_greasy_coating"]))
    turn = agent.run("这个病人是什么证型？")
    assert turn["rounds_used"] >= 2
    assert turn["multi_round"] is True
    assert "evidence_inquiry" in turn["subagents_used"]
    replans = [t for t in turn["transitions"] if t["to"] == "plan" and t["round"] >= 1]
    assert replans, "reflection must have routed back to planning"


def test_completeness_critic_covers_unexecuted_facets():
    # Single-intent question keyword plan (证型) but the question also asks about 风险:
    # the completeness critic queues the safety facet in a later round.
    agent = ReflectiveClinicalAgent(case_state=_case(["dark_tongue", "chronic_yabi", "lumbar_leg_pain"]))
    turn = agent.run("是什么证型？有什么用药安全风险？")
    assert {"syndrome_inquiry", "safety_inquiry"} <= set(turn["subagents_used"])


def test_rounds_are_capped():
    agent = ReflectiveClinicalAgent(case_state=_case(["elderly", "lumbar_knee_soreness", "chronic_yabi", "dark_tongue"]), max_rounds=1)
    turn = agent.run("是什么证型、方剂、风险、证据？")
    assert turn["rounds_used"] == 1
    assert turn["next_action"] in {"answer", "ask_followup", "abstain"}


# ------------------------------------------------------------------ safety hard veto

def test_confirmed_red_flag_escalates_and_withholds_decisions():
    agent = ReflectiveClinicalAgent(case_state=_case(["dark_tongue", "chronic_yabi"]))
    turn = agent.run("腰痛伴会阴麻木，尿不出来，是什么证型？")
    assert turn["next_action"] == "escalate"
    assert turn["candidate_decisions"] == []  # hard veto withholds clinical decisions
    assert turn["risk_state"]["safety_status"] == "urgent"
    assert any(f["severity"] == "veto" and f["critic"] == "safety" for f in turn["critic_findings"])
    assert "急诊" in turn["answer"]
    assert "证型" not in turn["answer"].split("危险信号")[0]


def test_denied_red_flags_do_not_escalate():
    agent = ReflectiveClinicalAgent(case_state=_case(["dark_tongue", "chronic_yabi", "lumbar_leg_pain"]))
    turn = agent.run("腰痛多年，否认外伤，无发热寒战，无大小便异常，是什么证型？")
    assert turn["next_action"] != "escalate"
    assert "外伤" in turn["risk_state"]["denied"]


# --------------------------------------------------------- uncertainty-driven inquiry

def test_sparse_case_asks_followup_instead_of_answering():
    agent = ReflectiveClinicalAgent(case_state=_case([]))
    turn = agent.run("我腰痛，帮我看看是什么证型")
    assert turn["next_action"] in {"ask_followup", "abstain"}
    if turn["next_action"] == "ask_followup":
        assert turn["followup_questions"]
        assert any("舌" in q or "疼痛" in q or "脉" in q for q in turn["followup_questions"])


def test_uncertain_red_flag_becomes_followup_question():
    agent = ReflectiveClinicalAgent(case_state=_case([]))
    turn = agent.run("腰痛一周，会不会发热？")
    assert turn["risk_state"]["uncertain"] == ["发热"]
    assert turn["next_action"] in {"ask_followup", "abstain"}
    assert any("发热" in q for q in turn["followup_questions"])


# ------------------------------------------------------------------ roles & endpoint

def test_patient_prescription_request_blocked():
    agent = ReflectiveClinicalAgent(case_state=_case([]), user_role="patient")
    turn = agent.run("直接给我开完整处方和剂量")
    assert turn["blocked"] is True
    assert turn["intent"] == "safety_block"


def test_reflective_endpoint_clinician(monkeypatch):
    server = _server(monkeypatch)
    res = server.handle_reflective({
        "question": "这个病人是什么证型，有什么风险？",
        "tags": ["dark_tongue", "chronic_yabi", "lumbar_leg_pain"], "doctor_mode": True,
    })
    turn = res["turn"]
    assert res["role"] == "clinician"
    assert turn["answer_source"] == "reflective_state_machine"
    assert turn["transitions"]
    assert turn["agent_state"]["next_action"] == turn["next_action"]


def test_reflective_endpoint_patient_is_whitelisted(monkeypatch):
    server = _server(monkeypatch)
    res = server.handle_reflective({"question": "是什么证型？", "tags": ["dark_tongue", "chronic_yabi"], "doctor_mode": False})
    turn = res["turn"]
    assert res["role"] == "patient"
    assert turn["medication_advice"] is None
    for leaked in ("agent_state", "transitions", "critic_findings", "candidate_decisions", "subagents_used"):
        assert leaked not in turn
