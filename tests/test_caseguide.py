from backend.skills.adaptive_question_planner_skill import adaptive_question_planner_skill
from backend.skills.caseguide_state_machine import CaseGuideSession
from backend.skills.consent_privacy_skill import consent_privacy_skill
from backend.skills.red_flag_screen_skill import red_flag_screen_skill
from backend.skills.patient_request_guard_skill import patient_request_guard_skill
from backend.skills.clinician_review_package_skill import clinician_review_package_skill


def build_complete_session():
    session = CaseGuideSession()
    session.start("姓名张三，电话13812345678，我腰痛")
    session.answer_red_flags({"RF001": "否", "RF002": "否", "RF003": "否", "RF004": "否", "RF005": "否", "RF006": "否"})
    session.answer_stage({"age": 68, "sex": "女", "main_symptom": "腰痛", "duration": "5年", "acute_worsening": "1月", "associated_symptom": "右下肢麻木", "recurrent_status": "反复发作，这次加重"})
    session.answer_stage({"P001": ["腰骶部"], "P002": "到小腿", "P003": ["酸痛", "麻痛"], "P004": 6, "P005": ["久坐", "受凉"], "P006": ["热敷"]})
    session.answer_stage({"N001": "经常有", "N002": ["小腿外侧"], "N003": "没有", "N004": "否", "N005": ["做过MRI", "做过骨密度"], "N006": ["骨质疏松"]})
    session.answer_stage({"T001": "怕冷", "T002": "遇冷加重，热敷舒服", "T004": "轻微", "T016": "睡不踏实", "T018": "胃口差", "T024": "偏暗紫", "T025": "白腻"})
    session.answer_stage({})
    session.answer_stage({"C001": ["骨质疏松", "高血压"], "C002": ["塞来昔布", "乙哌立松"], "C003": "否", "C004": "没有"})
    return session


def test_consent_desensitizes_and_preserves_boundary():
    result = consent_privacy_skill(raw_input="姓名张三，电话13812345678，地址北京市某区某街道，我想开方")
    assert "13812345678" not in result["sanitized_input"]
    assert "不构成诊断、处方或治疗建议" in result["required_homepage_notice"]
    assert "临床处方" in result["forbidden_outputs"]


def test_red_flag_screen_stops_on_urgent():
    result = red_flag_screen_skill({"RF001": "否", "RF002": "是", "RF003": "否", "RF004": "否", "RF005": "否", "RF006": "否"})
    assert result["red_flag_status"] == "urgent"
    assert result["next_action"] == "stop_and_refer"


def test_caseguide_generates_complete_case_and_handoff_without_prescription():
    session = build_complete_session()
    final = session.final_report()
    assert final["state"] == "S10_FINAL_REPORT"
    assert "腰痹医案草稿" in final["standard_case_markdown"]
    assert "医生复核摘要" in final["clinician_handoff_markdown"]
    assert "radiating_leg_pain" in final["case_state"]["normalized_tags"]
    assert final["shen_signals"]["danggui_sini_signal"] is True
    assert "不构成诊断、处方或治疗建议" in final["standard_case_markdown"]
    package = final["clinician_review_package"]
    assert package["diagnosis_review"]["non_final_diagnosis"] is True
    assert package["prescription_review"]["complete_prescription_generated"] is False
    assert package["prescription_review"]["patient_executable_dose_generated"] is False


def test_adaptive_planner_prioritizes_cold_heat_for_elderly_numbness_case():
    session = CaseGuideSession()
    session.case_state["patient_profile"]["age"] = 68
    session.case_state["chief_complaint"]["duration"] = "5年"
    session.case_state["normalized_tags"] = ["elderly", "chronic_yabi", "lower_limb_numbness", "osteoporosis"]
    result = adaptive_question_planner_skill(session.case_state, max_questions=3)
    questions = [item["question"]["question"] for item in result["next_questions"]]
    assert any("遇冷" in q or "热敷" in q for q in questions)


def test_patient_request_guard_blocks_final_diagnosis_prescription_and_dose():
    guard = patient_request_guard_skill("请给出最终诊断、完整处方和患者可执行剂量，标注需医师审核")
    assert guard["blocked"] is True
    assert set(guard["requested_outputs"]) == {"final_diagnosis", "complete_prescription", "patient_executable_dose"}
    assert "complete_clinical_prescription" in guard["forbidden_outputs"]
    package = clinician_review_package_skill({"normalized_tags": ["lower_limb_numbness"]}, requested_outputs=guard["requested_outputs"])["clinician_review_package"]
    assert package["request_guard"]["blocked"] is True
    assert package["prescription_review"]["complete_prescription_generated"] is False
    assert package["prescription_review"]["patient_executable_dose_generated"] is False


def test_physician_review_allows_signed_manual_content_and_rejects_model_generated():
    from backend.skills.physician_review_skill import create_physician_review_task, physician_review_skill

    case_state = {"normalized_tags": ["lower_limb_numbness"]}
    task = create_physician_review_task(case_state)["review_task"]
    assert task["status"] == "pending_physician_review"
    assert "final_diagnosis_generation" in task["model_forbidden_actions"]

    reviewer = {
        "role": "licensed_physician",
        "physician_id": "DOC-001",
        "physician_name": "审核医师",
        "license_id": "LICENSE-001",
        "signed": True,
    }
    rejected = physician_review_skill(
        case_state,
        reviewer,
        final_diagnosis={"source": "model_generated", "text": "腰椎间盘突出症"},
    )
    assert rejected["status"] == "rejected_model_generated_diagnosis"

    signed = physician_review_skill(
        case_state,
        reviewer,
        final_diagnosis={"source": "physician_entered", "text": "医师手工录入诊断"},
        prescription=[{"source": "physician_entered", "herb": "细辛", "dose": "医师手工录入剂量"}],
        administration={"source": "physician_entered", "text": "医师手工录入煎服法"},
    )["physician_review_record"]
    assert signed["status"] == "signed_physician_review"
    assert signed["audit"]["model_generated_complete_prescription"] is False
    assert signed["audit"]["physician_signed"] is True
    assert signed["warnings"]


def test_cdss_recommendation_generates_clinician_draft_not_signed_order():
    from backend.skills.cdss_recommendation_skill import cdss_recommendation_skill

    result = cdss_recommendation_skill(
        {"normalized_tags": ["lower_limb_numbness", "radiating_leg_pain"], "neuro_ortho": {"numbness": "经常有"}},
        syndrome_candidates=[{"name": "气血痹阻证", "score": 6, "evidence_tags": ["lower_limb_numbness"]}],
        formula_routes=[{"name": "当归四逆汤加减", "score": 5, "core_module": ["当归", "桂枝", "细辛"], "evidence_tags": ["lower_limb_numbness"]}],
        matched_modules=[{"name": "虫类搜络模块", "herbs": ["蜈蚣", "全蝎"], "evidence_tags": ["lower_limb_numbness"], "role": "add_on"}],
        user_role="clinician",
    )["cdss_recommendation"]
    assert result["status"] == "draft_for_clinician_review"
    assert result["patient_visible"] is False
    assert result["prescription_strategy_draft"]["complete_prescription_generated"] is False
    assert result["prescription_strategy_draft"]["patient_executable_dose_generated"] is False
    assert result["safety"]["high_risk_herbs_in_modules"] == ["全蝎", "蜈蚣"]


def test_cdss_recommendation_blocks_patient_role():
    from backend.skills.cdss_recommendation_skill import cdss_recommendation_skill

    result = cdss_recommendation_skill({"normalized_tags": []}, user_role="patient")["cdss_recommendation"]
    assert result["status"] == "blocked_patient_role"
    assert result["patient_visible"] is False
