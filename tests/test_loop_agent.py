"""Tests for the graph-backed agentic CDSS loop."""

from backend.agents.loop_agent import AgenticCDSSLoopAgent, ClinicalExperienceGraph


def _case():
    return {
        "normalized_tags": ["lower_limb_numbness", "cold_aggravation", "osteoporosis"],
        "chief_complaint": {"main_symptom": "腰痛", "standard_text": "腰痛伴下肢麻木"},
        "red_flags": {"status": "safe", "positive_items": []},
    }


def test_clinical_experience_graph_tracks_case_facts_and_observations():
    graph = ClinicalExperienceGraph()
    graph.update_from_case_state(_case(), "腰痛伴下肢麻木，遇冷加重", {"added_tags": ["cold_aggravation"]})
    snap = graph.snapshot()
    node_ids = {n["id"] for n in snap["nodes"]}
    assert "case_fact:lower_limb_numbness" in node_ids
    assert "case_fact:cold_aggravation" in node_ids
    assert any(e["relation"] == "updated_by" for e in snap["edges"])


def test_agentic_loop_builds_task_graph_and_clinician_package():
    agent = AgenticCDSSLoopAgent(case_state=_case(), max_rounds=2, max_steps_per_round=4)
    turn = agent.ask("这个病人证型、方剂路线和安全风险怎么综合判断？")
    assert turn["agentic"] is True
    assert turn["rounds"]
    first_tasks = turn["rounds"][0]["tasks"]
    assert any(t["task_type"] == "graph_update" for t in first_tasks)
    assert any(t["task_type"] == "subagent" for t in first_tasks)
    assert any(t["task_type"] == "critic" for t in first_tasks)
    assert any(t["task_type"] == "judge" for t in first_tasks)
    assert turn["decision"]["state"] in {"ready_for_clinician", "ask_followup", "abstain"}
    assert "自主智能体决策支持包" in turn["answer"]
    assert turn["graph"]["nodes"]


def test_agentic_loop_asks_gap_bound_followup_for_sparse_case():
    agent = AgenticCDSSLoopAgent(case_state={"normalized_tags": [], "red_flags": {"status": "safe", "positive_items": []}}, max_rounds=2)
    turn = agent.ask("腰痛怎么办？")
    assert turn["decision"]["state"] in {"ask_followup", "abstain"}
    if turn["decision"]["state"] == "ask_followup":
        assert turn["followup_questions"]
        assert all(q["target_gap"] for q in turn["followup_questions"])
        assert "下一轮自主问诊建议" in turn["answer"]


def test_agentic_loop_preserves_multi_turn_state():
    agent = AgenticCDSSLoopAgent(case_state={"normalized_tags": [], "red_flags": {"status": "safe", "positive_items": []}}, max_rounds=2)
    agent.ask("我主要是腰痛。")
    second = agent.ask("还伴下肢麻木，遇冷加重，想综合分析证型和方路。")
    tags = set(second["case_state"].get("normalized_tags") or [])
    assert "lower_limb_numbness" in tags
    assert "cold_aggravation" in tags
    assert second["graph"]["turn_index"] >= 2
