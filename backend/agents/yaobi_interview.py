"""YaoBi LLM-driven interview agent (Tao 模型 + Yao-Bi 智能体).

A conversational, frontier-style consultation FSM for the lumbar-Bi / low-back-and-leg-pain
domain. Each turn:

    用户自由文本
      → Tao 抽取结构化槽位 (DaoClient.extract_slots)
      → 合并到 YaoBiCaseState
      → 规则红旗筛查 (硬安全门控)
      → FSM 判断阶段 / 缺失槽位
      → 规则引擎给出候选证候 (syndrome_router, 用于鉴别性追问)
      → Tao 自主生成下一轮追问 (DaoClient.generate_interview_question)
      → 信息充分则用 Tao-primary 会诊生成报告 (tao_consultation_skill)

The language model is the primary reasoner (extraction / free-form follow-up / report);
the deterministic rule engine grounds candidate patterns, red flags and the safety floor.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.llm.dao_client import DaoClient, DaoRuntimeError
from backend.llm.json_repair import JsonRepairError, loads_with_repair
from backend.llm.output_guard import guard_consultation
from backend.skills.formula_base_selector_skill import formula_base_selector_skill
from backend.skills.herb_module_composer_skill import herb_module_composer_skill
from backend.skills.safety_guard_skill import safety_guard_skill
from backend.skills.syndrome_router_skill import syndrome_router_skill
from backend.skills.tao_consultation_skill import tao_consultation_skill


class YaoBiState(str, Enum):
    INIT = "INIT"
    SAFETY_TRIAGE = "SAFETY_TRIAGE"
    CHIEF_COMPLAINT = "CHIEF_COMPLAINT"
    PAIN_PROFILE = "PAIN_PROFILE"
    ORTHO_NEURO_SCREEN = "ORTHO_NEURO_SCREEN"
    TCM_PATTERN_COLLECTION = "TCM_PATTERN_COLLECTION"
    PAST_HISTORY = "PAST_HISTORY"
    TARGETED_FOLLOWUP = "TARGETED_FOLLOWUP"
    DECISION_OUTPUT = "DECISION_OUTPUT"
    SAFETY_REFERRAL = "SAFETY_REFERRAL"
    END = "END"


STATE_ORDER = [
    YaoBiState.SAFETY_TRIAGE, YaoBiState.CHIEF_COMPLAINT, YaoBiState.PAIN_PROFILE,
    YaoBiState.ORTHO_NEURO_SCREEN, YaoBiState.TCM_PATTERN_COLLECTION, YaoBiState.PAST_HISTORY,
    YaoBiState.TARGETED_FOLLOWUP,
]

STATE_GOAL = {
    YaoBiState.SAFETY_TRIAGE: "急危重症与红旗筛查",
    YaoBiState.CHIEF_COMPLAINT: "主诉与病程采集",
    YaoBiState.PAIN_PROFILE: "疼痛部位、性质、放射、诱因与缓解",
    YaoBiState.ORTHO_NEURO_SCREEN: "骨伤与神经压迫风险筛查",
    YaoBiState.TCM_PATTERN_COLLECTION: "中医寒热、湿、气血、舌脉等四诊信息",
    YaoBiState.PAST_HISTORY: "既往史、影像与用药史",
    YaoBiState.TARGETED_FOLLOWUP: "围绕候选证候的鉴别性追问",
    YaoBiState.DECISION_OUTPUT: "输出腰痹辅助决策报告",
    YaoBiState.SAFETY_REFERRAL: "高风险线下/急诊转诊提示",
}

# Required slots gating each FSM stage (slot resolved via the per-group dicts on the state).
REQUIRED_SLOTS = {
    YaoBiState.CHIEF_COMPLAINT: [("chief_complaint", None)],
    YaoBiState.PAIN_PROFILE: [("pain_slots", "pain_location"), ("pain_slots", "pain_nature"), ("pain_slots", "radiation")],
    YaoBiState.ORTHO_NEURO_SCREEN: [("pain_slots", "numbness"), ("pain_slots", "weakness")],
    YaoBiState.TCM_PATTERN_COLLECTION: [("tcm_slots", "cold_heat"), ("tcm_slots", "tongue_body"), ("tcm_slots", "pulse")],
    YaoBiState.PAST_HISTORY: [("history_slots", "western_diagnosis")],
}

# Slot → existing rule-engine tag, so the deterministic syndrome rules can score the case.
SLOT_TAGS: list[tuple[tuple[str, str], Any, list[str]]] = [
    (("pain_slots", "numbness"), True, ["lower_limb_numbness"]),
    (("pain_slots", "radiation"), True, ["radiating_leg_pain", "lumbar_leg_pain"]),
    (("pain_slots", "cold_damp_trigger"), True, ["cold_aggravation", "warmth_relieves"]),
    (("pain_slots", "trauma_history"), True, ["strain_or_sprain"]),
    (("pain_slots", "night_pain"), True, ["night_pain"]),
    (("pain_slots", "pain_nature"), "刺痛", ["stabbing_pain"]),
    (("pain_slots", "pain_nature"), "冷痛", ["cold_pain"]),
    (("tcm_slots", "fixed_pain"), True, ["fixed_pain"]),
    (("tcm_slots", "cold_heat"), "怕冷", ["cold_aggravation"]),
    (("tcm_slots", "limb_heaviness"), True, ["white_greasy_coating"]),
    (("tcm_slots", "waist_knee_soreness"), True, ["liver_kidney_deficiency"]),
    (("tcm_slots", "tongue_body"), "暗紫", ["dark_tongue", "purple_tongue"]),
    (("tcm_slots", "tongue_body"), "淡", ["pale_tongue"]),
    (("tcm_slots", "tongue_coating"), "白腻", ["white_greasy_coating"]),
    (("tcm_slots", "tongue_coating"), "黄腻", ["yellow_greasy_coating"]),
    (("history_slots", "osteoporosis"), True, ["osteoporosis"]),
]

# Discriminative slots per candidate pattern (drives the next follow-up target selection).
DISCRIMINATIVE = {
    "寒湿痹阻证": [("tcm_slots", "cold_pain"), ("pain_slots", "cold_damp_trigger"), ("tcm_slots", "tongue_coating")],
    "湿热痹阻证": [("tcm_slots", "tongue_coating"), ("tcm_slots", "thirst"), ("tcm_slots", "urine")],
    "气滞血瘀证": [("tcm_slots", "fixed_pain"), ("pain_slots", "pain_nature"), ("pain_slots", "night_pain")],
    "气血痹阻证": [("pain_slots", "radiation"), ("pain_slots", "numbness"), ("tcm_slots", "tongue_body")],
    "肝肾不足证": [("tcm_slots", "waist_knee_soreness"), ("pain_slots", "duration"), ("tcm_slots", "pulse")],
    "肾阳不足证": [("tcm_slots", "cold_heat"), ("tcm_slots", "urine"), ("tcm_slots", "stool")],
    "少阳证类": [("tcm_slots", "sleep"), ("tcm_slots", "thirst")],
}

SAFETY_SLOTS = [
    ("ortho_neuro_slots", "bowel_bladder_dysfunction"), ("ortho_neuro_slots", "saddle_anesthesia"),
    ("ortho_neuro_slots", "progressive_weakness"), ("ortho_neuro_slots", "severe_trauma"),
    ("ortho_neuro_slots", "fever"), ("ortho_neuro_slots", "tumor_history"),
]

MAX_TURNS = 8

# Deterministic red-flag keyword safety net: the LLM slot extractor is the primary
# channel, but red-flag detection must never depend on it alone — a missed slot key or
# an unexpected phrasing would otherwise let a cauda-equina presentation slip through.
RED_FLAG_TEXT_KEYWORDS: dict[str, list[str]] = {
    "bowel_bladder_dysfunction": ["大小便失禁", "小便失禁", "大便失禁", "尿不出", "解不出小便", "排尿困难", "大小便控制不"],
    "saddle_anesthesia": ["会阴麻木", "会阴部麻", "会阴发麻", "肛周麻木", "鞍区麻木"],
    "progressive_weakness": ["进行性无力", "越来越没力", "腿越来越软", "走路拖脚", "踩棉花感"],
    "severe_trauma": ["车祸", "摔伤", "高处坠落", "重物砸"],
    "fever": ["发烧", "发热", "寒战"],
    "tumor_history": ["肿瘤", "癌症"],
    "unexplained_weight_loss": ["体重下降", "不明原因消瘦"],
}
_NEGATION_MARKERS = ("没有", "没", "无", "不", "未", "否认", "排除")

# String slot values that mean "the patient denied it" — a red-flag slot holding
# "否"/"正常" must not count as positive (the LLM may return strings, not booleans).
_NEGATIVE_SLOT_STRINGS = {"否", "没有", "无", "正常", "不是", "没", "无异常", "否认", "阴性", "false", "no", "none", "unknown"}


def _slot_positive(value: Any) -> bool:
    """Truthiness for red-flag slots that treats denial strings as negative."""

    if isinstance(value, str):
        v = value.strip().lower()
        return bool(v) and v not in _NEGATIVE_SLOT_STRINGS and not v.startswith(("否", "没", "无", "不", "未"))
    return bool(value)


@dataclass
class YaoBiCaseState:
    session_id: str
    state: YaoBiState = YaoBiState.INIT
    turn_count: int = 0
    dialogue_history: list[dict[str, str]] = field(default_factory=list)
    demographics: dict[str, Any] = field(default_factory=dict)
    chief_complaint: Any = None
    pain_slots: dict[str, Any] = field(default_factory=dict)
    ortho_neuro_slots: dict[str, Any] = field(default_factory=dict)
    tcm_slots: dict[str, Any] = field(default_factory=dict)
    history_slots: dict[str, Any] = field(default_factory=dict)
    red_flags: list[str] = field(default_factory=list)
    safety_level: str = "unknown"
    candidate_patterns: list[dict[str, Any]] = field(default_factory=list)
    uncertainty_score: float = 1.0
    # Physician confirmation/revision/override of the safety referral.
    physician_review: dict[str, Any] = field(default_factory=dict)
    # Set to True by the override action so _detect_red_flags is bypassed for this session.
    red_flags_overridden: bool = False

    def group(self, name: str) -> dict[str, Any]:
        return getattr(self, name)

    def slot(self, group: str, key: str | None) -> Any:
        return self.chief_complaint if key is None else self.group(group).get(key)


class YaoBiInterviewEngine:
    def __init__(self, dao_client: DaoClient | None = None, use_llm: bool = False) -> None:
        self.dao_client = dao_client
        self.use_llm = use_llm

    # -- main turn ------------------------------------------------------------
    def run_turn(self, case: YaoBiCaseState, user_text: str) -> dict[str, Any]:
        user_text = (user_text or "").strip()
        if case.state == YaoBiState.INIT:
            case.state = YaoBiState.SAFETY_TRIAGE
        if user_text:
            case.dialogue_history.append({"role": "user", "content": user_text})
            case.turn_count += 1
            self._merge(case, self._extract(user_text))
            # Deterministic safety net: red flags mentioned in the raw text are captured
            # even when the LLM extractor is offline or missed the slot.
            self._scan_red_flag_text(case, user_text)

        self._detect_red_flags(case)
        if case.safety_level in ("high", "emergency"):
            case.state = YaoBiState.SAFETY_REFERRAL
            referral = self._build_referral(case)
            message = referral["message"]
            case.dialogue_history.append({"role": "assistant", "content": message})
            # Emergency (cauda equina) = hard terminal stop; high = advisory, user can clarify.
            return self._pack(case, message, done=(case.safety_level == "emergency"), referral=referral)

        case.state = self._transition(case)
        case.candidate_patterns, case.uncertainty_score = self._infer_patterns(case)

        if self._is_sufficient(case):
            report = self._build_report(case)
            case.state = YaoBiState.END
            case.dialogue_history.append({"role": "assistant", "content": report["answer"]})
            return self._pack(case, report["answer"], done=True, report=report)

        targets = self._select_target_slots(case)
        question = self._ask(case, targets)
        case.dialogue_history.append({"role": "assistant", "content": question})
        return self._pack(case, question, done=False, target_slots=targets)

    # -- Tao calls ------------------------------------------------------------
    def _extract(self, user_text: str) -> dict[str, Any]:
        if not self.use_llm:
            return {}
        client = self.dao_client or DaoClient()
        try:
            parsed, _ = loads_with_repair(client.extract_slots(user_text))
            return parsed if isinstance(parsed, dict) else {}
        except (DaoRuntimeError, JsonRepairError, ValueError, TypeError):
            return {}

    def _ask(self, case: YaoBiCaseState, targets: list[str]) -> str:
        deterministic = self._rule_question(case, targets)
        if not self.use_llm:
            return deterministic
        client = self.dao_client or DaoClient()
        try:
            text = (client.generate_interview_question({
                "stage": case.state.value,
                "stage_goal": STATE_GOAL.get(case.state, ""),
                "target_slots": targets,
                "candidate_patterns": case.candidate_patterns[:4],
                "case_summary": self._summary(case),
            }) or "").strip()
            return text or deterministic
        except DaoRuntimeError:
            return deterministic

    def _build_report(self, case: YaoBiCaseState) -> dict[str, Any]:
        # Full deterministic evidence bundle: the report scope covers 证型→治法→方药→随访,
        # so the model must be grounded in the rule engine's formula routes, herb modules
        # and safety review — not just syndrome candidates.
        tags = self._tags(case)
        candidates = [
            {"name": p["pattern"], "score": round(p["prob"] * 10, 1), "evidence_tags": p.get("evidence", [])}
            for p in case.candidate_patterns
        ]
        formula = formula_base_selector_skill(tags, candidates)
        routes = formula.get("formula_routes") or []
        modules = herb_module_composer_skill(tags, formula.get("primary_route"))
        matched = modules.get("matched_modules") or []
        safety = safety_guard_skill({"evidence": {"raw_text": self._case_text(case)}, "red_flags": case.red_flags}, matched, tags)
        evidence = {
            "normalized_tags": tags,
            "syndrome_candidates": candidates,
            "formula_routes": [{"name": r["name"], "confidence": r.get("confidence"), "score": r.get("score")} for r in routes[:4]],
            "herb_modules": [{"name": m["name"], "role": m.get("role"), "herbs": (m.get("herbs") or [])[:6]} for m in matched[:6]],
            "safety": {"status": safety.get("safety_status"), "risks": safety.get("medication_risks") or []},
            "case_state": self._summary(case),
            "red_flags": case.red_flags,
        }
        res = tao_consultation_skill(
            self._case_text(case), "腰痹全面会诊：证型→治法→方药→康复→随访（结合沈氏经验）",
            evidence, fallback_text=self._rule_report(case),
            dao_client=self.dao_client, use_llm=self.use_llm, user_role="clinician",
        )
        return res

    # -- rules / grounding ----------------------------------------------------
    def _merge(self, case: YaoBiCaseState, extracted: dict[str, Any]) -> None:
        if not isinstance(extracted, dict):
            return
        if extracted.get("chief_complaint") and not case.chief_complaint:
            case.chief_complaint = extracted["chief_complaint"]
        for group in ("demographics", "pain_slots", "ortho_neuro_slots", "tcm_slots", "history_slots"):
            incoming = extracted.get(group)
            if isinstance(incoming, dict):
                for key, value in incoming.items():
                    if value not in (None, "", [], "unknown"):
                        case.group(group)[key] = value

    def _scan_red_flag_text(self, case: YaoBiCaseState, user_text: str) -> None:
        """Deterministic keyword scan for red flags (union with LLM slot extraction).

        Simple negation handling: a keyword preceded closely by 没有/无/不/未 etc.
        ("没有大小便失禁") is treated as a denial and does not set the slot.
        """

        for slot, keywords in RED_FLAG_TEXT_KEYWORDS.items():
            if _slot_positive(case.ortho_neuro_slots.get(slot)):
                continue
            for keyword in keywords:
                idx = user_text.find(keyword)
                if idx == -1:
                    continue
                window = user_text[max(0, idx - 6):idx]
                if any(neg in window for neg in _NEGATION_MARKERS):
                    continue
                case.ortho_neuro_slots[slot] = True
                break

    def _detect_red_flags(self, case: YaoBiCaseState) -> None:
        if case.red_flags_overridden:
            case.red_flags = []
            case.safety_level = "low"
            return
        o, p, h = case.ortho_neuro_slots, case.pain_slots, case.history_slots
        flags: list[str] = []
        emergency = False
        # Cauda equina syndrome: hard stop, must go to ER immediately.
        # _slot_positive keeps a denial string ("否"/"正常") from firing a false emergency.
        if _slot_positive(o.get("bowel_bladder_dysfunction")):
            flags.append("大小便功能异常，需警惕马尾神经受压 → 立即急诊")
            emergency = True
        if _slot_positive(o.get("saddle_anesthesia")):
            flags.append("会阴区麻木，需警惕马尾神经受压 → 立即急诊")
            emergency = True
        # High-risk: serious but can be clarified/corrected by the user.
        if _slot_positive(o.get("progressive_weakness")):
            flags.append("进行性下肢无力，需排查神经受压")
        if _slot_positive(o.get("severe_trauma")):
            flags.append("明显外伤后腰痛，需排查骨折")
        if _slot_positive(h.get("osteoporosis")) and (_slot_positive(p.get("pain_severity")) or _slot_positive(o.get("severe_trauma"))):
            flags.append("骨质疏松合并急性剧痛，需排查压缩性骨折")
        if _slot_positive(o.get("fever")):
            flags.append("发热合并腰背痛，需排查感染")
        if _slot_positive(o.get("tumor_history")) and _slot_positive(p.get("night_pain")):
            flags.append("肿瘤病史合并夜间痛，需排查转移")
        if _slot_positive(o.get("unexplained_weight_loss")):
            flags.append("不明原因消瘦，需排查肿瘤")
        case.red_flags = flags
        case.safety_level = "emergency" if emergency else ("high" if flags else "low")

    def _has_missing(self, case: YaoBiCaseState, state: YaoBiState) -> bool:
        for group, key in REQUIRED_SLOTS.get(state, []):
            if case.slot(group, key) in (None, "", [], "unknown"):
                return True
        return False

    def _transition(self, case: YaoBiCaseState) -> YaoBiState:
        if case.state in (YaoBiState.END, YaoBiState.DECISION_OUTPUT):
            return case.state
        # advance through the ordered stages, stopping at the first with missing required slots
        for state in STATE_ORDER:
            if state == YaoBiState.TARGETED_FOLLOWUP:
                return YaoBiState.TARGETED_FOLLOWUP
            if self._has_missing(case, state):
                return state
        return YaoBiState.TARGETED_FOLLOWUP

    def _tags(self, case: YaoBiCaseState) -> list[str]:
        tags: set[str] = set()
        for (group, key), expected, mapped in SLOT_TAGS:
            value = case.slot(group, key)
            if value is None:
                continue
            if expected is True and value not in (False, None, "", "否"):
                tags.update(mapped)
            elif isinstance(expected, str) and isinstance(value, str) and expected in value:
                tags.update(mapped)
        age = case.demographics.get("age")
        if isinstance(age, (int, float)) and age >= 60:
            tags.add("elderly")
        dur = str((case.pain_slots.get("duration") or ""))
        if "年" in dur:
            tags.update({"chronic_yabi", "long_duration"})
        if case.pain_slots.get("pain_location"):
            tags.add("lumbar_pain")
        return sorted(tags)

    def _infer_patterns(self, case: YaoBiCaseState) -> tuple[list[dict[str, Any]], float]:
        cands = syndrome_router_skill(self._tags(case)).get("syndrome_candidates") or []
        scores = [max(0.1, float(c.get("score") or 1)) for c in cands]
        total = sum(scores) or 1.0
        patterns = [
            {"pattern": c["name"], "prob": round(s / total, 3), "evidence": c.get("evidence_tags", [])}
            for c, s in zip(cands, scores)
        ]
        probs = [p["prob"] for p in patterns if p["prob"] > 0]
        if probs:
            entropy = -sum(p * math.log(p + 1e-9) for p in probs)
            uncertainty = entropy / (math.log(len(probs)) + 1e-9) if len(probs) > 1 else 0.3
        else:
            uncertainty = 1.0
        return patterns, round(uncertainty, 3)

    def _select_target_slots(self, case: YaoBiCaseState) -> list[str]:
        unanswered = lambda pairs: [(k or g) for g, k in pairs if case.slot(g, k) in (None, "", [], "unknown")]
        # 1) required slots of the current FSM stage
        req = unanswered(REQUIRED_SLOTS.get(case.state, []))
        # 2) always make sure the core safety slots are covered
        safety = unanswered(SAFETY_SLOTS)
        # 3) discriminative slots for the leading candidate patterns
        disc_pairs: list[tuple[str, str]] = []
        for pattern in case.candidate_patterns[:3]:
            disc_pairs += DISCRIMINATIVE.get(pattern["pattern"], [])
        disc = unanswered(disc_pairs)
        ordered: list[str] = []
        for key in req + safety[:2] + disc:
            if key not in ordered:
                ordered.append(key)
        return ordered[:4] or ["pain_nature", "cold_heat", "tongue_body"]

    def _is_sufficient(self, case: YaoBiCaseState) -> bool:
        if case.turn_count >= MAX_TURNS:
            return True
        if case.state != YaoBiState.TARGETED_FOLLOWUP:
            return False
        if not case.candidate_patterns:
            return False
        top = case.candidate_patterns[0]["prob"]
        second = case.candidate_patterns[1]["prob"] if len(case.candidate_patterns) > 1 else 0.0
        clear = top > 0.5 and (top - second) > 0.12
        return clear or case.uncertainty_score < 0.5

    # -- deterministic fallbacks / formatting ---------------------------------
    def _rule_question(self, case: YaoBiCaseState, targets: list[str]) -> str:
        phrase = {
            "chief_complaint": "目前最主要的不适是什么、痛了多久了",
            "pain_location": "疼痛主要在腰部、臀部还是下肢", "pain_nature": "疼痛是酸痛、胀痛、刺痛还是冷痛",
            "radiation": "腰痛会不会向腿脚放射", "numbness": "腿脚有没有发麻", "weakness": "腿有没有发软无力",
            "cold_damp_trigger": "受凉或阴雨天会不会加重", "duration": "这次痛多久了",
            "cold_heat": "平时怕冷还是怕热", "tongue_body": "舌质偏淡、偏红还是偏暗紫",
            "tongue_coating": "舌苔是薄白、白腻还是黄腻", "pulse": "脉象偏细、偏弦还是偏沉",
            "waist_knee_soreness": "有没有腰膝酸软", "western_diagnosis": "之前医院诊断过什么",
            "bowel_bladder_dysfunction": "大小便是否正常", "fever": "有没有发热",
            "saddle_anesthesia": "会阴部有没有发麻", "progressive_weakness": "下肢无力是否进行性加重",
            "tumor_history": "有没有肿瘤病史或近期消瘦", "night_pain": "夜里痛得明显吗",
            "trauma_history": "近期有没有外伤", "stool": "大便情况", "urine": "小便清还是黄",
            "limb_heaviness": "肢体是否困重", "thirst": "口干口渴吗", "appetite": "胃口怎么样",
        }
        qs = [phrase.get(t, t) for t in targets][:4]
        return "想再了解几点：" + "；".join(qs) + "？"

    def _summary(self, case: YaoBiCaseState) -> dict[str, Any]:
        return {
            "demographics": case.demographics, "chief_complaint": case.chief_complaint,
            "pain": case.pain_slots, "ortho_neuro": case.ortho_neuro_slots,
            "tcm": case.tcm_slots, "history": case.history_slots,
        }

    def _case_text(self, case: YaoBiCaseState) -> str:
        return "；".join(m["content"] for m in case.dialogue_history if m["role"] == "user") or str(case.chief_complaint or "腰痛")

    def _rule_report(self, case: YaoBiCaseState) -> str:
        top = case.candidate_patterns[0]["pattern"] if case.candidate_patterns else "信息待补充"
        lines = [
            "# 腰痹问诊小结（确定性规则）", "",
            f"- 主诉：{case.chief_complaint or '腰痛'}",
            f"- 候选证候（倾向）：{('、'.join(p['pattern'] for p in case.candidate_patterns[:3]) or '待补充')}",
            f"- 安全状态：{case.safety_level}",
            "", "> 供执业医师审核，非最终诊断/处方。",
        ]
        return "\n".join(lines)

    def _build_referral(self, case: YaoBiCaseState) -> dict[str, Any]:
        """Rule-based safety warning + optional Tao emergency clinical guidance."""

        if case.safety_level == "emergency":
            action = "**请立即拨打急救电话（120）或前往最近急诊科**，本问诊终止常规辨证。"
        else:
            action = "建议尽快线下骨科/脊柱外科或急诊评估，本问诊暂停常规辨证。"
        base = "检测到需要重点排查的危险信号：\n- " + "\n- ".join(case.red_flags) + f"\n\n{action}"

        if not self.use_llm:
            return {"message": base, "tao_guidance": None, "used_llm": False, "source": "deterministic_rules"}

        client = self.dao_client or DaoClient()
        try:
            raw = client.generate_emergency_referral({
                "red_flags": case.red_flags,
                "safety_level": case.safety_level,
                "case_summary": self._summary(case),
            })
            text = (raw or "").strip()
            guard = guard_consultation(text, "clinician")
            if text and guard["allowed"]:
                full_message = base + "\n\n---\n\n" + text
                return {"message": full_message, "tao_guidance": text, "used_llm": True, "source": "tao_emergency_guidance"}
        except DaoRuntimeError:
            pass
        return {"message": base, "tao_guidance": None, "used_llm": False, "source": "deterministic_rules_fallback"}

    def run_review(
        self,
        case: "YaoBiCaseState",
        action: str,
        physician_notes: str = "",
        override_reason: str = "",
    ) -> dict[str, Any]:
        """Physician confirmation / revision / override of the safety referral.

        ``confirm``  — physician endorses the referral; interview remains stopped (done=True).
        ``revise``   — physician amends with notes; interview remains stopped (done=True).
        ``override`` — physician rejects the red-flag assessment; flags cleared, FSM resumes.
        """

        ts = int(time.time())
        if action == "confirm":
            case.physician_review = {
                "status": "confirmed",
                "physician_notes": physician_notes or "",
                "reviewed_at": ts,
            }
            note = f"（备注：{physician_notes}）" if physician_notes else ""
            message = f"医师已确认急诊转诊建议。{note}"
            case.dialogue_history.append({"role": "physician", "content": message})
            return self._pack(case, message, done=True)

        if action == "revise":
            case.physician_review = {
                "status": "revised",
                "physician_notes": physician_notes,
                "reviewed_at": ts,
            }
            message = f"医师已修订转诊建议。\n\n**医师备注：**{physician_notes}"
            case.dialogue_history.append({"role": "physician", "content": message})
            return self._pack(case, message, done=True)

        if action == "override":
            reason = override_reason or "医师评估后判断无需急诊转诊"
            case.physician_review = {
                "status": "overridden",
                "override_reason": reason,
                "physician_notes": physician_notes,
                "reviewed_at": ts,
            }
            # Bypass future red-flag detection for this session (physician has assessed).
            case.red_flags_overridden = True
            case.red_flags = []
            case.safety_level = "low"
            override_msg = f"医师已覆盖红旗评估，恢复问诊。\n**覆盖理由：**{reason}"
            case.dialogue_history.append({"role": "physician", "content": override_msg})
            # Resume the FSM — empty text triggers no slot extraction, just the next question.
            return self.run_turn(case, "")

        message = f"未知医师操作：{action}"
        return self._pack(case, message, done=False)

    def _pack(self, case: YaoBiCaseState, message: str, *, done: bool, report: dict[str, Any] | None = None, target_slots: list[str] | None = None, referral: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "session_id": case.session_id,
            "message": message,
            "state": case.state.value,
            "state_goal": STATE_GOAL.get(case.state, ""),
            "turn_count": case.turn_count,
            "safety_level": case.safety_level,
            "red_flags": case.red_flags,
            "candidate_patterns": case.candidate_patterns,
            "uncertainty": case.uncertainty_score,
            "case_summary": self._summary(case),
            "target_slots": target_slots or [],
            "done": done,
            "report": report["answer"] if report else None,
            "report_source": (report.get("source") if report else None),
            "used_llm": self.use_llm,
            # Emergency referral details (present when state == SAFETY_REFERRAL).
            "referral": referral,
            "referral_tao_guidance": (referral or {}).get("tao_guidance"),
            # Physician review state (persists across turns once set).
            "physician_review": case.physician_review,
            "physician_review_required": case.state == YaoBiState.SAFETY_REFERRAL and not case.physician_review.get("status"),
        }
