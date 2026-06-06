from backend.skills.pipeline import run_case_pipeline


def test_pipeline_matches_expected_rule_signals():
    result = run_case_pipeline("患者女，68岁，腰痛反复5年，加重1月，伴下肢麻木，畏寒，舌暗苔白腻，脉细缓，既往骨质疏松。")

    tags = set(result["normalized_tags"])
    assert "elderly" in tags
    assert "chronic_yabi" in tags
    assert "lower_limb_numbness" in tags
    assert "osteoporosis" in tags
    assert result["syndrome_candidates"][0]["name"] == "肝肾不足证"
    assert result["primary_route"]["name"] in {"独活寄生汤加减", "补肾类方", "当归四逆汤加减"}
    assert "不构成诊断、处方或治疗建议" in result["markdown_report"]


def test_safety_flags_raw_red_flag():
    result = run_case_pipeline("患者男，70岁，跌倒后腰痛，出现会阴麻木和尿不出来，想自己买药开方。")

    assert result["safety"]["safety_status"] == "urgent"
    messages = "\n".join(flag["message"] for flag in result["safety"]["red_flags"])
    assert "原文红旗线索" in messages
    assert "自行" in messages
