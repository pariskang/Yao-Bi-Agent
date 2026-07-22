"""Imaging/lab report skill and agent integration tests."""

from backend.agents.loop_agent import AgenticCDSSLoopAgent
from backend.agents.skill_router import keyword_route
from backend.llm.dao_client import DaoClient, DaoGenerationConfig
from backend.skills.imaging_report_skill import imaging_report_skill


def test_imaging_report_skill_extracts_findings_and_red_flags():
    res = imaging_report_skill(
        case_state={"normalized_tags": ["lower_limb_numbness"]},
        imaging_reports=[{"modality": "MRI", "text": "L4/5椎间盘突出，椎管狭窄，神经根受压。未见肿瘤。"}],
        lab_reports=[{"text": "CRP正常，血沉正常"}],
    )
    tags = {x["tag"] for x in res["key_findings"]}
    assert "disc_herniation" in tags
    assert "spinal_stenosis" in tags
    assert "nerve_root_compression" in tags
    assert "imaging_markdown" in res
    assert not res["red_flag_imaging_signals"]  # “未见肿瘤” must stay negative
    assert res["non_prescriptive"] is True


def test_imaging_report_skill_flags_affirmed_red_flag_terms():
    res = imaging_report_skill(imaging_reports=["腰椎MRI提示压缩骨折，需结合外伤史。"] )
    red_tags = {x["tag"] for x in res["red_flag_imaging_signals"]}
    assert "possible_fracture" in red_tags


def test_imaging_report_skill_uses_guarded_mock_llm_overlay():
    client = DaoClient(DaoGenerationConfig(backend="mock"))
    res = imaging_report_skill(
        case_state={},
        imaging_reports=["腰椎MRI提示椎间盘突出"],
        use_llm=True,
        dao_client=client,
    )
    assert res["llm_runtime"]["status"] == "accepted"
    assert res["source"] == "llm_guarded"
    assert "影像/检验检查评估" in res["imaging_markdown"]


def test_router_and_agentic_loop_plan_imaging_subagent():
    intent, _, hits = keyword_route("帮我读片：腰椎MRI报告提示椎间盘突出、椎管狭窄")
    assert intent == "imaging_report_inquiry"
    assert hits
    agent = AgenticCDSSLoopAgent(case_state={"normalized_tags": ["lower_limb_numbness"], "red_flags": {"status": "safe", "positive_items": []}}, max_rounds=1)
    turn = agent.ask("帮我读片：腰椎MRI报告提示L4/5椎间盘突出、椎管狭窄、神经根受压")
    assert "imaging_report_inquiry" in {s["intent"] for s in turn["steps"]}
    assert any("imaging_report_inquiry" in (n.get("id") or "") or n.get("label") == "读片/检查评估" for n in turn["graph"]["nodes"])
