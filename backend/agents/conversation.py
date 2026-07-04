"""Multi-turn conversational agent.

Each user turn: route the question to a registered skill (language model chooses from a
constrained intent list), then **autonomously invoke that skill** and answer from
deterministic rules / de-identified mined data. Returns transparency (which skill, how
routed, rule-vs-LLM) and suggested follow-up questions to guide the user.
"""

from __future__ import annotations

from typing import Any

from backend.agents.orchestrator import AgentOrchestrator
from backend.agents.skill_router import INTENT_BY_ID, INTENTS, route_intent, suggested_questions
from backend.llm.dao_client import DaoClient
from backend.skills.case_experience_summary_skill import case_experience_summary_skill
from backend.skills.conflict_checker_skill import conflict_checker_skill
from backend.skills.formula_base_selector_skill import formula_base_selector_skill
from backend.skills.herb_module_composer_skill import herb_module_composer_skill
from backend.skills.mined_evidence_skill import load_mined_rules, mined_evidence_skill
from backend.skills.physician_reasoning_skill import physician_reasoning_skill
from backend.skills.safety_guard_skill import safety_guard_skill
from backend.skills.syndrome_router_skill import syndrome_router_skill
from backend.skills.tao_consultation_skill import tao_consultation_skill
from backend.skills.uncertainty_skill import uncertainty_skill

# Clinical intents whose answer should be a Tao-primary grounded consultation (the model is
# the main reasoner) rather than a bare rule snippet. Scope guides the prompt per intent.
CONSULT_SCOPES = {
    "syndrome_inquiry": "证候辨析与病机分析",
    "formula_inquiry": "方剂路线、方义与随证加减",
    "herb_inquiry": "用药功效模块与配伍思路",
    "reasoning_inquiry": "辨证论治推理（症状→证候→治法→方药→安全）",
    "safety_inquiry": "用药安全、配伍禁忌与风险复核",
    "experience_inquiry": "医案按语与经验总结",
}

SYMPTOM_KEYWORD_TAG = {
    "麻木": "lower_limb_numbness", "放射": "radiating_leg_pain", "双下肢": "bilateral_leg_involvement",
    "遇冷": "cold_aggravation", "受凉": "cold_aggravation", "怕冷": "cold_aggravation",
    "口苦": "bitter_taste", "失眠": "insomnia", "乏力": "fatigue", "纳差": "poor_appetite",
    "高龄": "elderly", "骨质疏松": "osteoporosis",
}


def query_mined(question: str, mined: dict[str, Any]) -> dict[str, Any]:
    """Mine the de-identified dataset to answer a free-text question (根据提问挖掘)."""

    stats = mined.get("dataset_stats") or {}
    candidates = mined.get("rule_candidates") or []
    zheng = stats.get("zheng_distribution") or {}
    formula_routes = [c for c in candidates if c.get("rule_type") == "formula_route"]
    associations = [c for c in candidates if "association" in str(c.get("rule_type"))]

    # 1) syndrome name in the question
    for name, count in zheng.items():
        if name and name in question:
            routes = [c for c in formula_routes if c["statistics"].get("top_zheng") == name]
            assoc = [c for c in associations if c.get("if", {}).get("tag") == f"zheng::{name}"]
            lines = [f"「{name}」在脱敏样本中出现 **{count}** 例。"]
            if routes:
                lines.append("关联主方路线：" + "、".join(f"{c['then']['candidate_formula_route']}({c['statistics']['n_cases']}例)" for c in routes[:4]))
            if assoc:
                lines.append("关联规律：" + "；".join(f"{list(c['then'].values())[0]}(lift {c['statistics'].get('lift')})" for c in assoc[:4]))
            return {"answer": "\n\n".join(lines), "evidence": [c["rule_id"] for c in (routes + assoc)[:6]], "query_kind": "syndrome"}

    # 2) formula name
    for c in formula_routes:
        fname = c["then"]["candidate_formula_route"]
        if fname.split("(")[0] in question:
            st = c["statistics"]
            return {"answer": f"「{fname}」命中 **{st['n_cases']}** 张处方（support {st.get('support')}），主对应证型「{st.get('top_zheng')}」。", "evidence": [c["rule_id"]], "query_kind": "formula"}

    # 3) dose / herb
    dose = mined.get("dose_table") or {}
    for herb, d in dose.items():
        if herb in question:
            return {"answer": f"「{herb}」经验剂量分布：常用 {d['mode_g']} 克（{d['min_g']}–{d['max_g']} 克，n={d['n']}）。仅为医师端研究分布，非可执行医嘱。", "evidence": [herb], "query_kind": "dose"}

    # 4) symptom keyword -> association antecedent
    for kw, tag in SYMPTOM_KEYWORD_TAG.items():
        if kw in question:
            assoc = [c for c in associations if c.get("if", {}).get("tag") == tag]
            if assoc:
                lines = [f"「{kw}」相关的挖掘关联规律："]
                lines += [f"- {kw} → {list(c['then'].values())[0]}（support {c['statistics'].get('support')}，confidence {c['statistics'].get('confidence')}，lift {c['statistics'].get('lift')}）" for c in assoc[:5]]
                return {"answer": "\n".join(lines), "evidence": [c["rule_id"] for c in assoc[:5]], "query_kind": "symptom"}

    # 5) overview fallback
    top_z = "、".join(f"{k}({v})" for k, v in list(zheng.items())[:4]) or "—"
    top_f = "、".join(f"{c['then']['candidate_formula_route']}({c['statistics']['n_cases']})" for c in formula_routes[:4]) or "—"
    return {"answer": f"脱敏样本 {stats.get('n_cases', '—')} 例（含处方 {stats.get('n_with_prescription', '—')} 例）。高频证型：{top_z}。核心方剂路线：{top_f}。", "evidence": [], "query_kind": "overview"}


class ConversationSession:
    def __init__(self, case_state: dict[str, Any] | None = None, use_llm: bool = False, dao_client: DaoClient | None = None, user_role: str = "clinician") -> None:
        self.case_state = case_state or {}
        self.use_llm = use_llm
        self.dao_client = dao_client
        self.user_role = user_role
        self.history: list[dict[str, Any]] = []
        self._mined = load_mined_rules()

    # -- skill handlers (autonomously invoked after routing) --------------

    def _tags(self) -> list[str]:
        return self.case_state.get("normalized_tags", []) or []

    def _h_syndrome(self) -> dict[str, Any]:
        routed = syndrome_router_skill(self._tags())
        cands = routed.get("syndrome_candidates") or []
        if not cands:
            return {"answer": "当前病例信息不足以形成稳定证候倾向，建议补充舌脉与四诊。", "evidence": [], "skills": ["syndrome_router_skill"]}
        lines = ["候选证型（倾向，非最终诊断）："] + [f"- {c['name']}（{c.get('score')}分）：{('、'.join(c.get('evidence_tags', [])) or '—')}" for c in cands[:4]]
        return {"answer": "\n".join(lines), "evidence": cands[0].get("evidence_tags", []), "skills": ["syndrome_router_skill"]}

    def _h_formula(self) -> dict[str, Any]:
        routed = syndrome_router_skill(self._tags())
        formula = formula_base_selector_skill(self._tags(), routed.get("syndrome_candidates", []))
        routes = formula.get("formula_routes") or []
        if not routes:
            return {"answer": "暂无稳定方剂路线信号，建议补充关键证候变量。", "evidence": [], "skills": ["formula_base_selector_skill"]}
        lines = ["候选方剂路线信号（非处方）："] + [f"- {r['name']}（{r.get('confidence')}信度/{r.get('score')}分）" for r in routes[:4]]
        return {"answer": "\n".join(lines), "evidence": [r["name"] for r in routes[:4]], "skills": ["formula_base_selector_skill"]}

    def _h_herb(self) -> dict[str, Any]:
        routed = syndrome_router_skill(self._tags())
        formula = formula_base_selector_skill(self._tags(), routed.get("syndrome_candidates", []))
        modules = herb_module_composer_skill(self._tags(), formula.get("primary_route"))
        matched = modules.get("matched_modules") or []
        if not matched:
            return {"answer": "暂无匹配的用药功效模块，需补充信息。", "evidence": [], "skills": ["herb_module_composer_skill"]}
        lines = ["用药功效模块草案（需医师审核，无剂量）："] + [f"- {m['name']}（{m.get('role')}）：{('、'.join(m.get('herbs', [])[:6]))}" for m in matched[:6]]
        return {"answer": "\n".join(lines), "evidence": [m["name"] for m in matched[:6]], "skills": ["herb_module_composer_skill"]}

    def _h_safety(self) -> dict[str, Any]:
        routed = syndrome_router_skill(self._tags())
        formula = formula_base_selector_skill(self._tags(), routed.get("syndrome_candidates", []))
        modules = herb_module_composer_skill(self._tags(), formula.get("primary_route"))
        safety = safety_guard_skill({"evidence": {"raw_text": ""}, "red_flags": self.case_state.get("red_flags", {}).get("positive_items", [])}, modules.get("matched_modules"), self._tags())
        risks = safety.get("medication_risks") or []
        lines = [f"安全状态：**{safety.get('safety_status')}**。"]
        if risks:
            lines.append("高风险用药提示：" + "；".join(risks))
        if safety.get("red_flags"):
            lines.append("红旗线索：" + "；".join(f.get("message", "") for f in safety["red_flags"][:4]))
        return {"answer": "\n\n".join(lines), "evidence": risks, "skills": ["safety_guard_skill"]}

    def _h_red_flag(self) -> dict[str, Any]:
        status = (self.case_state.get("red_flags") or {}).get("status") or "未筛查"
        lines = [
            f"红旗筛查状态：**{status}**。需要立即排查的四类危险信号：",
            "- 马尾综合征：大小便障碍、会阴麻木 → 立即急诊",
            "- 肿瘤风险：肿瘤史、不明消瘦、夜间痛进行性加重",
            "- 感染风险：发热寒战、近期感染",
            "- 骨折风险：外伤、长期激素、重度骨质疏松骤发剧痛",
        ]
        return {"answer": "\n".join(lines), "evidence": (self.case_state.get("red_flags") or {}).get("positive_items", []), "skills": ["red_flag_screen_skill"]}

    def _h_dose(self, question: str) -> dict[str, Any]:
        res = query_mined(question, self._mined)
        if res["query_kind"] != "dose":
            res = {"answer": "请指定药物，如“细辛/附片/全蝎在数据里常用多少量”。剂量为医师端研究分布，非可执行医嘱。", "evidence": [], "query_kind": "dose"}
        return {"answer": res["answer"], "evidence": res.get("evidence", []), "skills": ["xlsx_dose_mining"]}

    def _h_mining(self, question: str) -> dict[str, Any]:
        if not self._mined:
            return {"answer": "尚未加载脱敏挖掘数据，请先运行挖掘管道生成 rules/11_mined_rule_candidates.yaml。", "evidence": [], "skills": ["xlsx_case_miner"]}
        res = query_mined(question, self._mined)
        return {"answer": res["answer"], "evidence": res.get("evidence", []), "skills": ["xlsx_case_miner"]}

    def _h_evidence(self) -> dict[str, Any]:
        routed = syndrome_router_skill(self._tags())
        ev = mined_evidence_skill(self._tags(), routed.get("syndrome_candidates", []))
        rules = ev.get("mined_evidence") or []
        if not rules:
            return {"answer": "当前病例标签未匹配到挖掘候选规则。", "evidence": [], "skills": ["mined_evidence_skill"]}
        lines = ["匹配到的挖掘候选规则（待专家审核）："] + [f"- {r['rule_id']}：{list(r.get('then', {}).values())[0] if r.get('then') else ''}（lift {r.get('statistics', {}).get('lift', '—')}）" for r in rules[:6]]
        return {"answer": "\n".join(lines), "evidence": [r["rule_id"] for r in rules[:6]], "skills": ["mined_evidence_skill"]}

    def _h_reasoning(self) -> dict[str, Any]:
        routed = syndrome_router_skill(self._tags())
        formula = formula_base_selector_skill(self._tags(), routed.get("syndrome_candidates", []))
        modules = herb_module_composer_skill(self._tags(), formula.get("primary_route"))
        pr = physician_reasoning_skill(self.case_state, routed.get("syndrome_candidates", []), formula.get("formula_routes"), modules.get("matched_modules"), dao_client=self.dao_client, use_llm=False)["physician_reasoning"]
        chain = pr.get("reasoning_chain") or []
        lines = ["辨证推理链（倾向性，非最终诊断）："] + [f"{s['step']}. {s['title']}：{s['content']}" for s in chain]
        return {"answer": "\n".join(lines), "evidence": [s["title"] for s in chain], "skills": ["physician_reasoning_skill"], "used_llm": False}

    def _h_experience(self) -> dict[str, Any]:
        routed = syndrome_router_skill(self._tags())
        formula = formula_base_selector_skill(self._tags(), routed.get("syndrome_candidates", []))
        modules = herb_module_composer_skill(self._tags(), formula.get("primary_route"))
        ce = case_experience_summary_skill(self.case_state, routed.get("syndrome_candidates", []), formula.get("formula_routes"), modules.get("matched_modules"), mode="case", dao_client=self.dao_client, use_llm=False)["case_experience_summary"]
        return {"answer": ce.get("summary_markdown", ""), "evidence": ce.get("key_points", []), "skills": ["case_experience_summary_skill"], "used_llm": False}

    def _h_agent(self) -> dict[str, Any]:
        roster = AgentOrchestrator().describe()
        lines = ["多智能体在共享黑板上自主协作（规则为主、语言模型受守卫）："] + [f"- {a['name']}（{a['role']}/{a['kind']}）→ {('、'.join(a['handoff_to']))}" for a in roster]
        lines.append("红旗智能体命中急诊信号时自主中止下游临床智能体，仅急诊提示续跑。")
        return {"answer": "\n".join(lines), "evidence": [a["name"] for a in roster], "skills": ["AgentOrchestrator"]}

    def _h_capabilities(self) -> dict[str, Any]:
        lines = ["你可以这样问我（点击下方示例也可）："]
        for grp in suggested_questions():
            lines.append(f"**{grp['group']}**：" + "；".join(f"「{ex}」" for it in grp["items"] for ex in it["examples"][:1]))
        return {"answer": "\n".join(lines), "evidence": [], "skills": ["skill_router"]}

    # -- routing + dispatch ----------------------------------------------

    def _evidence_bundle(self) -> dict[str, Any]:
        """Gather the deterministic rule/mined evidence that grounds the Tao consultation."""

        tags = self._tags()
        routed = syndrome_router_skill(tags)
        cands = routed.get("syndrome_candidates") or []
        formula = formula_base_selector_skill(tags, cands)
        routes = formula.get("formula_routes") or []
        modules = herb_module_composer_skill(tags, formula.get("primary_route"))
        matched = modules.get("matched_modules") or []
        safety = safety_guard_skill(
            {"evidence": {"raw_text": ""}, "red_flags": (self.case_state.get("red_flags") or {}).get("positive_items", [])},
            matched, tags,
        )
        mined = mined_evidence_skill(tags, cands).get("mined_evidence") or []
        uncertainty = uncertainty_skill(cands, tags)["uncertainty"]
        comorbidity = self.case_state.get("comorbidity") or {}
        interactions = conflict_checker_skill(
            matched, formula.get("primary_route"),
            medications=comorbidity.get("medications") or [],
            conditions=comorbidity.get("diseases") or [],
        )
        return {
            "normalized_tags": tags,
            "syndrome_candidates": [{"name": c["name"], "score": c.get("score"), "evidence_tags": c.get("evidence_tags", [])} for c in cands[:4]],
            "formula_routes": [{"name": r["name"], "confidence": r.get("confidence"), "score": r.get("score")} for r in routes[:4]],
            "herb_modules": [{"name": m["name"], "role": m.get("role"), "herbs": (m.get("herbs") or [])[:6]} for m in matched[:6]],
            "safety": {"status": safety.get("safety_status"), "risks": safety.get("medication_risks") or []},
            "interaction_alerts": [
                {"level": a.get("alert_level"), "description": a.get("description")}
                for a in (interactions.get("interaction_alerts") or [])[:5]
            ],
            "mined_evidence": [{"rule_id": r.get("rule_id"), "then": r.get("then")} for r in mined[:6]],
            "shen_signals": (self.case_state.get("shen_signals") or [])[:6],
            # The consultation prompt sees the engine's own confidence assessment, so the
            # model can (and should) voice low separation or abstention instead of bluffing.
            "uncertainty": {
                "abstain": uncertainty.get("abstain"),
                "assessment_note": uncertainty.get("assessment_note"),
                "differential_gaps": [g.get("suggestion") for g in uncertainty.get("differential_gaps") or []],
            },
        }

    def _consult(self, intent: str, question: str, det: dict[str, Any], full: bool) -> dict[str, Any]:
        """Replace the bare rule answer with a Tao-primary grounded consultation."""

        scope = "全面会诊：证型→治法→方药→安全（结合沈氏经验）" if full else CONSULT_SCOPES[intent]
        res = tao_consultation_skill(
            question, scope, self._evidence_bundle(),
            fallback_text=det["answer"], dao_client=self.dao_client, use_llm=self.use_llm, user_role=self.user_role,
        )
        return {
            "answer": res["answer"], "evidence": det.get("evidence", []), "skills": det.get("skills", []),
            "used_llm": res["used_llm"], "consult_source": res["source"], "tao_runtime": res.get("tao_runtime"),
            # Faithfulness transparency: rule-backed vs model-own-knowledge entities.
            "groundedness": res.get("groundedness"), "semantic_consistency": res.get("semantic_consistency"),
        }

    def _dispatch(self, intent: str, question: str, full: bool = False) -> dict[str, Any]:
        handlers = {
            "syndrome_inquiry": self._h_syndrome, "formula_inquiry": self._h_formula,
            "herb_inquiry": self._h_herb, "safety_inquiry": self._h_safety,
            "red_flag_inquiry": self._h_red_flag, "evidence_inquiry": self._h_evidence,
            "reasoning_inquiry": self._h_reasoning, "experience_inquiry": self._h_experience,
            "agent_inquiry": self._h_agent, "capabilities": self._h_capabilities,
        }
        if intent in ("mining_inquiry",):
            return self._h_mining(question)
        if intent == "dose_inquiry":
            return self._h_dose(question)
        det = handlers.get(intent, self._h_capabilities)()
        # Clinical intents: the model becomes the primary reasoner, grounded in rule evidence.
        if self.use_llm and intent in CONSULT_SCOPES:
            return self._consult(intent, question, det, full)
        return det

    def invoke(self, intent: str, question: str = "") -> dict[str, Any]:
        """Public subagent entry: run one skill handler for a given intent.

        Used by the autonomous multi-step agent to delegate a sub-task to the
        subagent responsible for ``intent`` (constrained to the registered set).
        """

        if intent not in INTENT_BY_ID:
            intent = "capabilities"
        result = self._dispatch(intent, question)
        meta = INTENT_BY_ID.get(intent, {})
        return {
            "intent": intent,
            "label": meta.get("label", intent),
            "group": meta.get("group"),
            "answer": result["answer"],
            "skills": result.get("skills", []),
            "evidence": result.get("evidence", []),
            "used_llm": bool(result.get("used_llm")),
        }

    def starters(self) -> list[dict[str, Any]]:
        return suggested_questions()

    def ask(self, question: str) -> dict[str, Any]:
        routing = route_intent(question, use_llm=self.use_llm, dao_client=self.dao_client, user_role=self.user_role)
        if routing["blocked"]:
            answer = routing["guard"]["message"]
            turn = {
                "question": question, "intent": "safety_block", "intent_label": "安全拦截",
                "method": routing["method"], "answer": answer, "skills": ["patient_request_guard_skill"],
                "evidence": [], "used_llm": False, "routing": routing,
                "suggested_followups": ["有哪些危险信号需要排查？", "可以考虑哪些方剂路线？"],
            }
            self.history.append(turn)
            return turn

        intent = routing["intent"]
        meta = INTENT_BY_ID.get(intent, {})
        result = self._dispatch(intent, question, full=True)
        followups = [ex for other in INTENTS if other["intent"] != intent for ex in other["examples"][:1]][:4]
        turn = {
            "question": question, "intent": intent, "intent_label": meta.get("label", intent),
            "intent_group": meta.get("group"), "method": routing["method"], "confidence": routing["confidence"],
            "answer": result["answer"], "skills": result.get("skills", []), "evidence": result.get("evidence", []),
            "used_llm": bool(result.get("used_llm")), "llm_routing": routing["llm_runtime"],
            "answer_source": result.get("consult_source", "deterministic_rules"), "consult_runtime": result.get("tao_runtime"),
            "groundedness": result.get("groundedness"), "semantic_consistency": result.get("semantic_consistency"),
            "matched_keywords": routing.get("matched_keywords", []),
            "suggested_followups": followups,
            "disclaimer": "语言模型结合沈氏经验规则与脱敏挖掘数据进行辨证论治分析（供执业医师审核）；患者端不提供最终诊断、完整处方或可执行剂量。",
        }
        self.history.append(turn)
        return turn
