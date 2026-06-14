"""Tests for the HTTP server that bridges the UI to the genuine Tao-in-the-loop backend.

With ``TAO_BACKEND=mock`` the language-model path actually runs (route_skill / plan_skills /
generate_followup_probes / orchestrator LLM agents), so these assert the model genuinely
drives skill selection — not the client-side keyword stubs — while safety stays enforced.
"""

from __future__ import annotations

import importlib


def _server(monkeypatch, backend: str = "mock"):
    monkeypatch.setenv("TAO_BACKEND", backend)
    import backend.server as server_module

    return importlib.reload(server_module)


def test_health_reports_tao_runtime(monkeypatch):
    server = _server(monkeypatch)
    health = server.handle_health({})
    assert health["ok"] is True
    assert health["tao"]["enabled"] is True
    assert health["tao"]["backend"] == "mock"


def test_chat_routes_via_language_model(monkeypatch):
    server = _server(monkeypatch)
    turn = server.handle_chat({"question": "这个病人偏向什么证型？", "tags": ["dark_tongue", "chronic_yabi"], "doctor_mode": True})["turn"]
    assert turn["method"] == "llm"
    assert turn["llm_routing"]["status"] == "accepted"
    assert "syndrome_router_skill" in turn["skills"]


def test_chat_extracts_tags_from_free_text(monkeypatch):
    server = _server(monkeypatch)
    # No intake tags supplied: the candidates must come from extracting the typed question.
    turn = server.handle_chat({
        "question": "腰腿痛、下肢麻木、遇冷加重、舌暗、苔白腻、高龄、骨质疏松，是什么证型？",
        "tags": [], "doctor_mode": True,
    })["turn"]
    assert turn["intent"] == "syndrome_inquiry"
    assert "信息不足" not in turn["answer"]


def test_autonomous_plans_via_language_model(monkeypatch):
    server = _server(monkeypatch)
    turn = server.handle_autonomous({"question": "是什么证型、用什么方、有什么风险？", "tags": ["lower_limb_numbness", "cold_aggravation"], "doctor_mode": True})["turn"]
    assert turn["plan_method"] == "llm"
    assert turn["multi_step"] is True
    assert len(turn["plan"]) >= 2


def test_followup_probe_generates_rule_bounded_probes(monkeypatch):
    server = _server(monkeypatch)
    res = server.handle_followup_probe({"stage": "pain", "tags": ["cold_aggravation"], "doctor_mode": True, "budget": 2})
    assert res["tao_probe_runtime"]["status"] == "accepted"
    assert res["probes"]
    assert all(p["source"] == "tao_probe" for p in res["probes"])


def test_followup_probe_not_applicable_for_redflag(monkeypatch):
    server = _server(monkeypatch)
    res = server.handle_followup_probe({"stage": "redflag", "tags": [], "doctor_mode": True})
    assert res["tao_probe_runtime"]["status"] == "not_applicable"
    assert res["probes"] == []


def test_collaboration_runs_llm_agents(monkeypatch):
    server = _server(monkeypatch)
    res = server.handle_collaboration({"tags": ["lower_limb_numbness", "dark_tongue", "chronic_yabi"], "doctor_mode": True})
    assert res["agent_count"] >= 10
    assert res["llm_in_loop"] is True
    assert "ReasoningAgent" in res["used_llm_agents"]
    assert "blackboard" not in res  # internal working memory is stripped for the UI


def test_patient_request_for_prescription_is_blocked(monkeypatch):
    server = _server(monkeypatch)
    turn = server.handle_chat({"question": "直接给我开完整处方和剂量", "tags": [], "doctor_mode": False})["turn"]
    assert turn["intent"] == "safety_block"


def test_disabled_backend_is_offline(monkeypatch):
    server = _server(monkeypatch, backend="disabled")
    assert server.TAO_ENABLED is False
    assert server.handle_health({})["tao"]["enabled"] is False
