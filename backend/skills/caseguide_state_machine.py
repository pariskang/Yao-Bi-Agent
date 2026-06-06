from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.skills.adaptive_question_planner_skill import adaptive_question_planner_skill
from backend.skills.case_quality_check_skill import case_quality_check_skill
from backend.skills.case_structuring_skill import case_structuring_skill
from backend.skills.caseguide_utils import apply_answer, empty_case_state, load_caseguide_questions
from backend.skills.chief_complaint_skill import chief_complaint_skill
from backend.skills.clinician_handoff_skill import clinician_handoff_skill
from backend.skills.clinician_review_package_skill import clinician_review_package_skill
from backend.skills.cdss_recommendation_skill import cdss_recommendation_skill
from backend.skills.comorbidity_medication_skill import comorbidity_medication_skill
from backend.skills.consent_privacy_skill import consent_privacy_skill
from backend.skills.neuro_ortho_screen_skill import neuro_ortho_screen_skill
from backend.skills.pain_profile_skill import pain_profile_skill
from backend.skills.red_flag_screen_skill import red_flag_screen_skill
from backend.skills.shen_rule_signal_skill import shen_rule_signal_skill
from backend.skills.tcm_four_diagnosis_skill import tcm_four_diagnosis_skill
from backend.skills.case_normalize_skill import case_normalize_skill
from backend.skills.formula_base_selector_skill import formula_base_selector_skill
from backend.skills.herb_module_composer_skill import herb_module_composer_skill
from backend.skills.safety_guard_skill import safety_guard_skill
from backend.skills.syndrome_router_skill import syndrome_router_skill

STATES = {
    "S0_CONSENT": {"goal": "知情提示、非诊疗声明、隐私脱敏", "next": "S1_REDFLAG"},
    "S1_REDFLAG": {"goal": "排除需要立即就医的危险信号", "next_if_safe": "S2_BASIC", "next_if_danger": "S_EMERGENCY_NOTICE"},
    "S2_BASIC": {"goal": "采集年龄、性别、职业、主诉、病程", "next": "S3_PAIN_PROFILE"},
    "S3_PAIN_PROFILE": {"goal": "采集疼痛部位、性质、程度、诱因、缓解因素", "next": "S4_NEURO_ORTHO"},
    "S4_NEURO_ORTHO": {"goal": "采集放射痛、麻木、无力、大小便、影像诊断", "next": "S5_TCM_CORE"},
    "S5_TCM_CORE": {"goal": "采集中医寒热、湿、气血、舌象、脉象等信息", "next": "S6_SHEN_SIGNAL"},
    "S6_SHEN_SIGNAL": {"goal": "针对沈老经验规则补问高价值变量", "next": "S7_COMORBIDITY"},
    "S7_COMORBIDITY": {"goal": "采集骨质疏松、糖尿病、高血压、NSAIDs、肌松药等", "next": "S8_ADAPTIVE_REPAIR"},
    "S8_ADAPTIVE_REPAIR": {"goal": "动态补问缺失字段", "next": "S9_CASE_SUMMARY"},
    "S9_CASE_SUMMARY": {"goal": "生成医案草稿，让患者确认", "next": "S10_FINAL_REPORT"},
    "S10_FINAL_REPORT": {"goal": "输出标准化医案、标签、规则命中、医生复核清单"},
}


@dataclass
class CaseGuideSession:
    state: str = "S0_CONSENT"
    case_state: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.case_state is None:
            self.case_state = empty_case_state()

    def start(self, raw_input: str = "", user_role: str = "patient") -> dict[str, Any]:
        consent = consent_privacy_skill(user_role=user_role, raw_input=raw_input)
        self.state = "S1_REDFLAG"
        return {"state": self.state, **consent, "questions": load_caseguide_questions().get("red_flag_questions", [])[:3]}

    def answer_red_flags(self, answers: dict[str, Any]) -> dict[str, Any]:
        result = red_flag_screen_skill(answers)
        self.case_state["red_flags"] = {"status": result["red_flag_status"], "positive_items": result["positive_flags"]}
        self.state = "S_EMERGENCY_NOTICE" if result["red_flag_status"] == "urgent" else "S2_BASIC"
        return {"state": self.state, **result, "next_questions": self.next_questions()}

    def answer_stage(self, answers: dict[str, Any]) -> dict[str, Any]:
        if self.state == "S2_BASIC":
            self._apply_basic_answers(answers)
            self.state = "S3_PAIN_PROFILE"
        elif self.state == "S3_PAIN_PROFILE":
            self.case_state = pain_profile_skill(self.case_state, answers)["case_state"]
            self.state = "S4_NEURO_ORTHO"
        elif self.state == "S4_NEURO_ORTHO":
            result = neuro_ortho_screen_skill(self.case_state, answers)
            self.case_state = result["case_state"]
            self.state = "S5_TCM_CORE"
        elif self.state == "S5_TCM_CORE":
            self.case_state = tcm_four_diagnosis_skill(self.case_state, answers)["case_state"]
            self.state = "S6_SHEN_SIGNAL"
        elif self.state == "S6_SHEN_SIGNAL":
            self.case_state = shen_rule_signal_skill(self.case_state)["case_state"]
            self.state = "S7_COMORBIDITY"
        elif self.state == "S7_COMORBIDITY":
            self.case_state = comorbidity_medication_skill(self.case_state, answers)["case_state"]
            self.state = "S8_ADAPTIVE_REPAIR"
        elif self.state == "S8_ADAPTIVE_REPAIR":
            self._apply_any_answers(answers)
            self.state = "S9_CASE_SUMMARY"
        return {"state": self.state, "case_state": self.case_state, "next_questions": self.next_questions()}

    def next_questions(self, max_questions: int = 3) -> list[dict[str, Any]]:
        if self.state == "S2_BASIC":
            return load_caseguide_questions().get("chief_complaint_questions", [])[:max_questions]
        if self.state == "S3_PAIN_PROFILE":
            return load_caseguide_questions().get("pain_questions", [])[:max_questions]
        if self.state == "S4_NEURO_ORTHO":
            return load_caseguide_questions().get("neuro_ortho_questions", [])[:max_questions]
        if self.state == "S5_TCM_CORE":
            return load_caseguide_questions().get("tcm_four_diagnosis_questions", [])[:max_questions]
        if self.state == "S7_COMORBIDITY":
            return load_caseguide_questions().get("comorbidity_questions", [])[:max_questions]
        if self.state == "S8_ADAPTIVE_REPAIR":
            return [item["question"] for item in adaptive_question_planner_skill(self.case_state, max_questions)["next_questions"]]
        return []

    def final_report(self) -> dict[str, Any]:
        shen = shen_rule_signal_skill(self.case_state)
        self.case_state = shen["case_state"]
        quality = case_quality_check_skill(self.case_state)
        self.case_state = quality["case_state"]
        normalized_tags = self.case_state.get("normalized_tags", [])
        routed = syndrome_router_skill(normalized_tags)
        formula = formula_base_selector_skill(normalized_tags, routed["syndrome_candidates"])
        modules = herb_module_composer_skill(normalized_tags, formula.get("primary_route"))
        safety = safety_guard_skill({"evidence": {"raw_text": ""}, "red_flags": self.case_state.get("red_flags", {}).get("positive_items", [])}, modules["matched_modules"], normalized_tags)
        structured = case_structuring_skill(self.case_state)
        handoff = clinician_handoff_skill(self.case_state, formula.get("formula_routes"), modules["matched_modules"], safety)
        review_package = clinician_review_package_skill(
            self.case_state,
            routed["syndrome_candidates"],
            formula.get("formula_routes"),
            modules["matched_modules"],
            safety,
        )
        cdss = cdss_recommendation_skill(
            self.case_state,
            routed["syndrome_candidates"],
            formula.get("formula_routes"),
            modules["matched_modules"],
            safety,
            user_role="clinician",
        )
        self.state = "S10_FINAL_REPORT"
        return {"state": self.state, "case_state": self.case_state, "shen_signals": shen["shen_signals"], "high_value_missing": shen["high_value_missing"], **quality, **routed, **formula, **modules, "safety": safety, **structured, **handoff, **review_package, **cdss}

    def _apply_basic_answers(self, answers: dict[str, Any]) -> None:
        self.case_state["patient_profile"]["age"] = answers.get("age", self.case_state["patient_profile"].get("age"))
        self.case_state["patient_profile"]["sex"] = answers.get("sex", self.case_state["patient_profile"].get("sex"))
        self.case_state["patient_profile"]["occupation"] = answers.get("occupation", self.case_state["patient_profile"].get("occupation"))
        self.case_state["patient_profile"]["physical_labor"] = answers.get("physical_labor", self.case_state["patient_profile"].get("physical_labor"))
        chief = chief_complaint_skill(
            main_symptom=answers.get("main_symptom"),
            duration=answers.get("duration"),
            recurrent_status=answers.get("recurrent_status"),
            acute_worsening=answers.get("acute_worsening"),
            associated_symptom=answers.get("associated_symptom"),
        )
        self.case_state["chief_complaint"].update({
            "main_symptom": answers.get("main_symptom"),
            "duration": answers.get("duration"),
            "acute_worsening": answers.get("acute_worsening"),
            "recurrent_status": answers.get("recurrent_status"),
            "standard_text": chief["chief_complaint"],
        })
        if isinstance(answers.get("age"), int):
            if answers["age"] >= 60:
                self.case_state.setdefault("normalized_tags", []).append("elderly")
            if answers["age"] >= 73:
                self.case_state.setdefault("normalized_tags", []).append("very_elderly")
        if answers.get("duration") and "年" in str(answers["duration"]):
            self.case_state.setdefault("normalized_tags", []).extend(["chronic_yabi", "long_duration"])
        self.case_state["normalized_tags"] = sorted(set(self.case_state.get("normalized_tags", [])))

    def _apply_any_answers(self, answers: dict[str, Any]) -> None:
        by_id = {q["id"]: q for q in sum([v for k, v in load_caseguide_questions().items() if k.endswith("_questions")], [])}
        for qid, answer in answers.items():
            if qid in by_id:
                self.case_state = apply_answer(self.case_state, by_id[qid], answer)
