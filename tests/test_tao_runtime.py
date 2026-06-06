from backend.llm.dao_client import DaoClient, DaoGenerationConfig
from backend.llm.json_repair import loads_with_repair
from backend.llm.output_guard import guard_tao_output
from backend.skills.pipeline import run_case_pipeline
from backend.skills.tao_report_generation_skill import tao_report_generation_skill


class BrokenJsonDaoClient(DaoClient):
    def __init__(self, text: str):
        super().__init__(DaoGenerationConfig(backend="mock"))
        self.text = text

    def generate(self, structured_rule_outputs):
        return self.text


def test_json_repair_handles_fenced_trailing_comma_and_single_quotes():
    parsed, meta = loads_with_repair("""```json
    {'markdown_report': '教学解释', 'final_diagnosis': null,}
    ```""")
    assert parsed["markdown_report"] == "教学解释"
    assert parsed["final_diagnosis"] is None
    assert meta["repaired"] is True


def test_tao_overlay_accepts_repaired_safe_json():
    safe = """以下为结果：
    {'markdown_report': '本案为规则命中教学解释，不构成诊断、处方或治疗建议。',
     'final_diagnosis': null,
     'complete_prescription': null,
     'patient_executable_dose': null,}
    """
    result = run_case_pipeline(
        "患者女，68岁，腰痛反复5年，加重1月，伴下肢麻木，畏寒，舌暗苔白腻，脉细缓，既往骨质疏松。",
        use_llm=True,
        dao_client=BrokenJsonDaoClient(safe),
    )
    assert result["tao_runtime"]["status"] == "accepted"
    assert result["tao_runtime"]["json_repair"]["repaired"] is True
    assert result["tao_runtime"]["fallback_used"] is False
    assert "Tao 教学解释补充" in result["markdown_report"]


def test_tao_overlay_rejects_prescriptive_output_and_falls_back():
    unsafe = '{"markdown_report": "最终诊断为腰椎间盘突出症，处方如下：细辛3g，水煎服。", "final_diagnosis": "腰椎间盘突出症"}'
    result = run_case_pipeline("患者男，50岁，腰痛伴腿麻。", use_llm=True, dao_client=BrokenJsonDaoClient(unsafe))
    assert result["tao_runtime"]["status"] == "guard_rejected"
    assert result["tao_runtime"]["fallback_used"] is True
    assert "最终诊断为腰椎间盘突出症" not in result["markdown_report"]


def test_tao_disabled_runtime_falls_back_to_deterministic_report():
    result = run_case_pipeline("患者女，68岁，腰痛反复5年。", use_llm=True, dao_client=DaoClient(DaoGenerationConfig(backend="disabled")))
    assert result["tao_runtime"]["status"] == "fallback"
    assert result["tao_runtime"]["fallback_used"] is True
    assert "沈钦荣腰痹经验规则分析报告" in result["markdown_report"]


def test_guard_detects_diagnosis_prescription_and_dose_patterns():
    guard = guard_tao_output("最终诊断为腰痹，处方如下：细辛3g，每日2次。")
    categories = {item["category"] for item in guard["violations"]}
    assert {"final_diagnosis", "patient_executable_prescription", "dose_instruction"}.issubset(categories)
