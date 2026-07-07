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


def test_chat_answer_is_tao_primary_deep_consultation(monkeypatch):
    # The model becomes the main reasoner: a long grounded consultation, never "信息不足".
    server = _server(monkeypatch)
    turn = server.handle_chat({
        "question": "患者青年女性，跌扑后腰肌劳损，遇冷加重，舌淡红，苔薄白，脉细，什么证型、用什么方？",
        "tags": [], "doctor_mode": True,
    })["turn"]
    assert turn["answer_source"] == "tao_primary_grounded"
    assert turn["used_llm"] is True
    assert len(turn["answer"]) > 200
    assert "信息不足" not in turn["answer"]
    assert "##" in turn["answer"]  # structured professional answer


def test_followup_probe_is_model_generated_freeform(monkeypatch):
    server = _server(monkeypatch)
    res = server.handle_followup_probe({"stage": "pain", "tags": ["cold_aggravation"], "budget": 2, "doctor_mode": True})
    runtime = res["tao_probe_runtime"]
    assert runtime["status"] == "accepted"
    assert runtime.get("mode") == "freeform"
    assert res["probes"]
    assert all(p["source"] == "tao_probe" for p in res["probes"])


def _interview(server, sid, msg):
    return server.handle_interview({"session_id": sid, "message": msg})


def test_interview_is_llm_driven_fsm_to_report(monkeypatch):
    # Tao extracts slots, the FSM advances, Tao asks follow-ups, then emits a report.
    server = _server(monkeypatch)
    server.handle_interview({"session_id": "iv", "reset": True})
    # With the damp-cold/damp-heat rules the posterior is flatter for this mixed
    # presentation, so the agent keeps asking discriminating questions (the intended
    # uncertainty behaviour) — the transcript answers them until the report is emitted.
    msgs = [
        "腰痛反复多年，舌暗紫，苔白腻，遇冷加重",
        "腰部酸胀痛，向左腿放射，左小腿发麻，没有无力",
        "怕冷，腰膝酸软，热敷舒服，脉细",
        "之前诊断腰椎间盘突出，做过核磁，没有大小便异常，无发热无肿瘤史",
        "双腿沉重，肢体困重，阴雨天加重明显",
        "夜里不痛，白天活动后加重",
        "口不苦，无口干，不口渴",
        "胃口可以，睡眠一般，小便清",
    ]
    states, last = [], None
    for m in msgs:
        last = _interview(server, "iv", m)
        states.append(last["state"])
        if last["done"]:
            break
    assert "PAIN_PROFILE" in states  # FSM moved past chief complaint
    assert last["done"] is True
    assert last["report_source"] == "tao_primary_grounded"
    assert last["report"] and len(last["report"]) > 200
    assert last["candidate_patterns"]


def test_interview_red_flag_hard_stop(monkeypatch):
    server = _server(monkeypatch)
    server.handle_interview({"session_id": "rf", "reset": True})
    res = _interview(server, "rf", "腰痛伴大小便失禁，会阴麻木，下肢进行性无力")
    assert res["state"] == "SAFETY_REFERRAL"
    # Bowel/bladder + saddle anesthesia = cauda equina emergency → "emergency" level + done=True.
    assert res["safety_level"] == "emergency"
    assert res["done"] is True
    assert res["red_flags"]
    assert "急诊" in res["message"]


def test_interview_negation_does_not_trigger_red_flag(monkeypatch):
    server = _server(monkeypatch)
    server.handle_interview({"session_id": "ng", "reset": True})
    res = _interview(server, "ng", "腰痛，没有大小便异常，无发热，无外伤")
    assert res["safety_level"] == "low"
    assert res["state"] != "SAFETY_REFERRAL"


def test_interview_emergency_referral_includes_tao_guidance(monkeypatch):
    """With mock backend, emergency referral should include Tao clinical guidance."""
    server = _server(monkeypatch)
    server.handle_interview({"session_id": "tao_rf", "reset": True})
    res = _interview(server, "tao_rf", "大小便失禁，会阴麻木")
    assert res["safety_level"] == "emergency"
    assert res["referral_tao_guidance"] is not None          # Tao added ER guidance
    assert "急诊转诊" in res["referral_tao_guidance"]         # expected section header
    assert "紧迫度" in res["referral_tao_guidance"]           # urgency classification present
    assert "physician_review_required" in res
    assert res["physician_review_required"] is True          # physician must review


def test_interview_high_risk_referral_tao_guidance(monkeypatch):
    """Non-cauda-equina high-risk flag: safety_level=high (not emergency), done=False."""
    server = _server(monkeypatch)
    server.handle_interview({"session_id": "high_rf", "reset": True})
    res = _interview(server, "high_rf", "腰背痛伴发热寒战，肿瘤病史，夜间痛加重")
    assert res["safety_level"] == "high"
    assert res["done"] is False                              # advisory, user can clarify
    assert res["referral_tao_guidance"] is not None          # Tao still provides guidance


def test_interview_physician_confirm(monkeypatch):
    """Physician confirm action marks the referral as endorsed and keeps done=True."""
    server = _server(monkeypatch)
    server.handle_interview({"session_id": "ph_c", "reset": True})
    _interview(server, "ph_c", "大小便失禁，会阴麻木")      # triggers emergency
    res = server.handle_interview({
        "session_id": "ph_c",
        "review_action": "confirm",
        "physician_notes": "已联系120，患者正在转运",
    })
    assert res["physician_review"]["status"] == "confirmed"
    assert "已联系120" in res["physician_review"]["physician_notes"]
    assert res["done"] is True


def test_interview_physician_revise(monkeypatch):
    """Physician revise action replaces guidance with physician-authored note."""
    server = _server(monkeypatch)
    server.handle_interview({"session_id": "ph_r", "reset": True})
    _interview(server, "ph_r", "大小便失禁，会阴麻木")
    res = server.handle_interview({
        "session_id": "ph_r",
        "review_action": "revise",
        "physician_notes": "建议收住脊柱外科病房，暂不急诊手术",
    })
    assert res["physician_review"]["status"] == "revised"
    assert "脊柱外科" in res["physician_review"]["physician_notes"]
    assert res["done"] is True


def test_health_reports_model_load_lifecycle(monkeypatch):
    # /api/health now exposes load_state/model_loaded so a client can poll readiness instead of
    # holding one long warmup request open and seeing only "Connection refused" when it fails.
    server = _server(monkeypatch)
    tao = server.handle_health({})["tao"]
    assert tao["load_state"] == "ready"  # mock backend needs no weights
    assert "model_loaded" in tao
    assert "load_error" in tao


def test_should_preload_prefers_flag_then_env_then_backend(monkeypatch):
    server = _server(monkeypatch)
    # Explicit --preload/--no-preload wins over everything.
    assert server._should_preload(True, "mock") is True
    assert server._should_preload(False, "transformers") is False
    # Then TAO_PRELOAD env.
    monkeypatch.setenv("TAO_PRELOAD", "1")
    assert server._should_preload(None, "mock") is True
    monkeypatch.setenv("TAO_PRELOAD", "off")
    assert server._should_preload(None, "transformers") is False
    # Default (no flag, no env): eager only for the heavy transformers backend.
    monkeypatch.delenv("TAO_PRELOAD", raising=False)
    assert server._should_preload(None, "transformers") is True
    assert server._should_preload(None, "mock") is False


def test_warmup_reports_disabled_backend_cleanly(monkeypatch):
    # Disabled backend must answer warmup with a reason (ok=False), never crash the request.
    server = _server(monkeypatch, backend="disabled")
    res = server.handle_warmup({})
    assert res["ok"] is False
    assert "reason" in res


def test_interview_physician_override_resumes_fsm(monkeypatch):
    """Physician override clears red flags and the FSM resumes asking clinical questions."""
    server = _server(monkeypatch)
    server.handle_interview({"session_id": "ph_o", "reset": True})
    _interview(server, "ph_o", "大小便失禁，会阴麻木")      # triggers emergency
    res = server.handle_interview({
        "session_id": "ph_o",
        "review_action": "override",
        "override_reason": "患者描述有误，实际无膀胱症状",
    })
    # Red flags cleared; FSM resumes normal questioning
    assert res["safety_level"] == "low"
    assert res["state"] != "SAFETY_REFERRAL"
    assert res["physician_review"]["status"] == "overridden"
    assert "无膀胱症状" in res["physician_review"]["override_reason"]
    assert res["done"] is False                              # interview continues
