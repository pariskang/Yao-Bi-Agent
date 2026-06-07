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
    assert "Math.min(2, value)" in app
    assert "CDSS" in app
    assert "@media" in css
