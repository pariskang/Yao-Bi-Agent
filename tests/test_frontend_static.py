from pathlib import Path


def test_frontend_static_ui_contains_required_caseguide_surfaces():
    root = Path("frontend")
    index = (root / "index.html").read_text(encoding="utf-8")
    app = (root / "app.js").read_text(encoding="utf-8")
    css = (root / "styles.css").read_text(encoding="utf-8")

    assert "YaoBi-CaseGuide" in index
    assert "实时医案草稿" in index
    assert "安全边界" in index
    assert "draft_for_clinician_review" in app
    assert "patient_visible=False" not in app  # UI uses human-readable boundary text, not Python literals.
    assert "不构成最终诊断、签名处方或患者可执行剂量" in app
    assert "红旗筛查" in app
    assert "有限状态机追问" in app
    assert "手动结束本状态" in app
    assert "本状态深化追问" in app
    assert "Tao" in app
    assert "Tao Direct Runtime" in app
    assert "TAO_BACKEND=transformers" in app
    assert "JSON Repair" in index + app
    assert "Output Guard" in index + app
    assert "Physician Review" in app
    assert "data-tab=\"cdss\"" in app
    assert "data-tab=\"physician\"" in app
    assert "stageRound" in app
    assert "maxRounds" in app  # 追问轮数上限可配置，不再硬编码 3 轮。
    assert "追问轮数上限" in app
    assert "答完自动进入下一状态" in app
    assert "maybeAutoAdvance" in app
    assert "CDSS" in app
    assert "@media" in css


def test_frontend_presents_all_modules_and_mined_rules():
    root = Path("frontend")
    index = (root / "index.html").read_text(encoding="utf-8")
    app = (root / "app.js").read_text(encoding="utf-8")
    mined = (root / "mined_rules.js").read_text(encoding="utf-8")

    # 模块导航：所有模块都在 UI 呈现
    assert "moduleNav" in index and "moduleNav" in app
    for label in ["总览看板", "智能问诊", "规则挖掘", "证据回溯", "医师审核", "评估与安全", "设置"]:
        assert label in app
    assert "mined_rules.js" in index
    assert "MINED_RULES" in app and "window.MINED_RULES" in mined

    # 挖掘产物必须是脱敏聚合：含统计字段、不含 PII 字段名
    for key in ["rule_candidates", "support", "confidence", "lift", "pending_expert_review"]:
        assert key in mined
    for pii in ["病案号", "patient_name", "地址：", "电话"]:
        assert pii not in mined

    # 安全边界在挖掘/审核模块同样呈现
    assert "不构成诊断或处方依据" in app
    assert "pending_expert_review" in app


def test_frontend_presents_tao_reasoning_and_summary_modules():
    root = Path("frontend")
    app = (root / "app.js").read_text(encoding="utf-8")

    # 新增模块导航与视图
    for label in ["经验推理", "经验总结"]:
        assert label in app
    assert "renderReasoningModule" in app
    assert "renderSummaryModule" in app

    # Tao 规则约束内自动追问
    assert "Tao 自动追问" in app
    assert "taoProbesFor" in app
    assert "TAO_PROBE_" in app
    assert "tao-probe" in app

    # 推理链与经验总结呈现
    assert "辨证推理链" in app
    assert "buildReasoningChain" in app
    assert "医案按语" in app

    # 最终报告新增推理/按语标签
    assert 'data-tab="reasoning"' in app
    assert 'data-tab="summary"' in app

    # 安全边界仍在
    assert "draft_for_clinician_review" in app
    assert "非最终诊断" in app


def test_frontend_presents_agent_collaboration_module():
    root = Path("frontend")
    app = (root / "app.js").read_text(encoding="utf-8")

    assert "智能体协作" in app
    assert "renderAgentsModule" in app
    assert "buildAgentTrace" in app
    # 协作机制要素：共享黑板、自主中止、语言模型在环、人类终审
    for token in ["共享黑板", "自主中止", "语言模型在环", "EmergencyNoticeAgent", "PhysicianReviewAgent"]:
        assert token in app
    # 规则/语言模型标识与时间轴
    assert "agent-timeline" in app
    assert "kind-badge" in app
    assert "ReasoningAgent" in app and "ExperienceAgent" in app
