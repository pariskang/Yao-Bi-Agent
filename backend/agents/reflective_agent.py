"""Multi-round reflective clinical agent — an explicit, contract-validated state machine.

This is the full plan-execute-observe-reflect-replan loop the single-pass autonomous
agent approximates. The entire agent lifecycle lives in one unified, auditable state
(``backend.contracts.AGENT_STATE``)::

    {
      "goal": "...",
      "known_facts": [...],          # affirmed clinical facts (normalized tags)
      "negated_facts": [...],        # pertinent negatives — never re-asked, never alarmed
      "uncertain_facts": [...],      # unresolved mentions → follow-up material
      "risk_state": {...},           # graded safety assessment (confirmed/denied/uncertain)
      "candidate_decisions": [...],  # syndrome candidates w/ evidence chains
      "tool_plan": [...],            # intents queued for the next EXECUTE round
      "observations": [...],         # every tool call's contract-validated result
      "critic_findings": [...],      # safety / evidence / uncertainty / completeness critics
      "next_action": "plan | execute | reflect | ask_followup | answer | escalate | abstain",
      "transitions": [...]           # full state-machine audit trail
    }

State machine::

    UNDERSTAND → PLAN → EXECUTE → REFLECT ─┬→ PLAN (critics queued new tools, rounds left)
                                           ├→ ESCALATE (safety critic hard veto)
                                           ├→ ASK_FOLLOWUP (abstention + resolvable gaps)
                                           ├→ ABSTAIN (insufficient evidence, nothing to ask)
                                           └→ ANSWER

Reflection runs four deterministic critics every round:

* **safety critic** — recomputes the graded risk state; an urgent verdict is a *hard
  veto*: the loop terminates in ESCALATE and no clinical decision content is emitted;
* **evidence critic** — flags observations with no rule/mined evidence and candidate
  decisions whose contradicting evidence rivals their support (conflicts become
  follow-up questions, not silently averaged scores);
* **uncertainty critic** — abstention / narrow top-2 separation queues discriminating
  tools for the next round and surfaces the missing differential facts;
* **completeness critic** — intents the question implies but no round has executed yet
  are queued for the next round.

Termination is guaranteed: rounds are capped (``max_rounds``), every tool runs at most
once, and a reflection pass that queues nothing must choose a terminal action.
"""

from __future__ import annotations

from typing import Any

from backend.agents.conversation import ConversationSession
from backend.agents.skill_router import INTENT_BY_ID
from backend.agents.autonomous_agent import plan_question
from backend.contracts import AGENT_STATE, validate
from backend.llm.dao_client import DaoClient
from backend.skills.case_extract_skill import case_extract_skill
from backend.skills.case_normalize_skill import case_normalize_skill
from backend.skills.patient_request_guard_skill import patient_request_guard_skill
from backend.skills.safety_guard_skill import safety_guard_skill
from backend.skills.syndrome_router_skill import syndrome_router_skill
from backend.skills.uncertainty_skill import uncertainty_skill

_MISSING_FIELD_QUESTIONS = {
    "疼痛性质": "疼痛更像酸痛、胀痛、刺痛还是冷痛？",
    "是否放射痛": "腰痛会不会向臀部或腿脚放射？",
    "夜寐": "睡眠怎么样，夜里会不会痛醒？",
    "胃纳": "胃口怎么样？",
    "二便": "大小便是否正常？",
    "舌象": "舌质偏淡、偏红还是偏暗紫，舌苔是薄白、白腻还是黄腻？",
    "脉象": "如果号过脉，脉象偏细、偏弦还是偏沉？",
}

_DISCLAIMER = "反思型智能体基于确定性规则与脱敏数据循环推理；输出为供执业医师审核的研究草案，不构成最终诊断、处方或可执行剂量。"


class ReflectiveClinicalAgent:
    """Goal-driven clinical agent with an explicit multi-round reflection loop."""

    def __init__(
        self,
        case_state: dict[str, Any] | None = None,
        use_llm: bool = False,
        dao_client: DaoClient | None = None,
        user_role: str = "clinician",
        max_rounds: int = 3,
    ) -> None:
        self.session = ConversationSession(case_state=case_state, use_llm=use_llm, dao_client=dao_client, user_role=user_role)
        self.use_llm = use_llm
        self.dao_client = dao_client
        self.user_role = user_role
        self.max_rounds = max(1, min(int(max_rounds), 5))

    # ------------------------------------------------------------------ state helpers

    def _transition(self, state: dict[str, Any], to: str, why: str) -> None:
        state["transitions"].append({"round": state["round"], "from": state["next_action"], "to": to, "why": why})
        state["next_action"] = to
        validate(state, AGENT_STATE, "reflective_agent.transition")

    def _queue_tool(self, state: dict[str, Any], intent: str, reason: str) -> bool:
        """Queue a tool for the next round; every intent runs at most once per session."""

        if intent in state["executed_tools"] or any(t["intent"] == intent for t in state["tool_plan"]):
            return False
        if intent not in INTENT_BY_ID:
            return False
        state["tool_plan"].append({"intent": intent, "reason": reason})
        return True

    # ------------------------------------------------------------------ UNDERSTAND

    def _understand(self, question: str) -> dict[str, Any]:
        case_facts = case_extract_skill(question)
        extracted_tags = case_normalize_skill(case_facts)["normalized_tags"]
        case_tags = self.session.case_state.get("normalized_tags") or []
        known = sorted(set(case_tags) | set(extracted_tags))
        # Tools reason over the merged fact base, not just the intake questionnaire.
        self.session.case_state["normalized_tags"] = known
        risk_text = (case_facts.get("evidence") or {}).get("raw_text", "")
        # Narrative candidates (polarity-resolved) plus questionnaire positives — the
        # latter arrive pre-confirmed by the intake UI, so they enter as affirmed.
        entities = list(case_facts["red_flag_entities"]) + [
            {"entity": str(term), "polarity": "affirmed", "category": None}
            for term in (self.session.case_state.get("red_flags") or {}).get("positive_items") or []
        ]
        risk_state = safety_guard_skill(
            {"evidence": {"raw_text": risk_text}, "red_flag_entities": entities}, None, known,
        )
        state: dict[str, Any] = {
            "goal": f"围绕问题「{question[:60]}」给出规则接地、安全分级、可解释的辅助分析或追问。",
            "round": 0,
            "max_rounds": self.max_rounds,
            "known_facts": known,
            "negated_facts": sorted(set(case_facts["denied_red_flags"])),
            "uncertain_facts": sorted(set(case_facts["uncertain_red_flags"])),
            "risk_state": risk_state,
            "candidate_decisions": [],
            "tool_plan": [],
            "executed_tools": [],
            "observations": [],
            "critic_findings": [],
            "next_action": "understand",
            "transitions": [],
            "missing_fields": case_facts.get("missing_fields") or [],
        }
        self._transition(state, "plan", "已建立事实基线（肯定/否定/待澄清）与风险状态。")
        return state

    # ------------------------------------------------------------------ PLAN / EXECUTE

    def _plan(self, state: dict[str, Any], question: str) -> None:
        state["round"] += 1
        if not state["tool_plan"]:
            planned = plan_question(question, max_steps=3, use_llm=self.use_llm, dao_client=self.dao_client)
            state["plan_runtime"] = planned["llm_runtime"]
            state["plan_method"] = planned["method"]
            for step in planned["plan"]:
                self._queue_tool(state, step["intent"], step.get("reason", ""))
        if not state["tool_plan"]:
            self._transition(state, "reflect", "无新工具可规划，直接进入反思判定终态。")
            return
        self._transition(state, "execute", f"第 {state['round']} 轮计划 {len(state['tool_plan'])} 个工具。")

    def _execute(self, state: dict[str, Any], question: str) -> None:
        batch, state["tool_plan"] = state["tool_plan"], []
        for step in batch:
            observation = self.session.invoke(step["intent"], question)
            observation["round"] = state["round"]
            observation["reason"] = step.get("reason", "")
            state["observations"].append(observation)
            state["executed_tools"].append(step["intent"])
        self._transition(state, "reflect", f"第 {state['round']} 轮执行完毕，进入批判者反思。")

    # ------------------------------------------------------------------ REFLECT (critics)

    def _finding(self, state: dict[str, Any], critic: str, severity: str, finding: str, recommendation: str = "") -> None:
        record = {"critic": critic, "severity": severity, "finding": finding}
        if recommendation:
            record["recommendation"] = recommendation
        state["critic_findings"].append(record)

    def _reflect(self, state: dict[str, Any], question: str) -> None:
        # 1) Safety critic — hard veto power over every other outcome.
        risk = state["risk_state"]
        if risk["safety_status"] == "urgent":
            self._finding(state, "safety", "veto",
                          "确认级红旗（" + "、".join(f.get("term") or f.get("id", "") for f in risk["confirmed_red_flags"][:4]) + "）命中，硬否决常规辨证输出。",
                          "立即急诊/线下评估；本轮不输出证型与方药内容。")
            self._transition(state, "escalate", "安全批判者硬否决：确认级红旗。")
            return
        if risk["safety_status"] == "caution" and self._queue_tool(state, "red_flag_inquiry", "安全批判者：存在待复核风险线索，补充红旗排查。"):
            self._finding(state, "safety", "warning", "风险状态为 caution 且尚未执行红旗排查。", "追加 red_flag_inquiry。")
        else:
            # A passing verdict is still a verdict: every reflection pass leaves an
            # explicit safety ruling in the audit trail.
            self._finding(
                state, "safety", "info",
                f"第 {state['round']} 轮安全裁定：{risk['safety_status']}"
                f"（确认红旗 {len(risk['confirmed_red_flags'])}，已否认 {len(risk['denied_red_flags'])}，待澄清 {len(risk['uncertain_red_flags'])}）。",
            )

        # 2) Evidence critic — refresh decisions from the merged fact base and audit them.
        candidates = syndrome_router_skill(state["known_facts"]).get("syndrome_candidates") or []
        state["candidate_decisions"] = candidates
        ungrounded = [o["intent"] for o in state["observations"] if not o.get("evidence")]
        if ungrounded:
            self._finding(state, "evidence", "info", f"{len(ungrounded)} 个观察缺乏规则/挖掘证据支撑：{ '、'.join(sorted(set(ungrounded))[:4]) }。")
        conflicted = [c for c in candidates if c.get("contradicting_evidence")]
        for candidate in conflicted[:2]:
            self._finding(
                state, "evidence", "warning",
                f"候选「{candidate['name']}」存在反证：{'、'.join(candidate['contradicting_evidence'][:4])}。",
                "证据冲突不得静默平均——转为面向用户的澄清追问。",
            )

        # 3) Uncertainty critic — abstention & separation drive follow-up and replanning.
        uncertainty = uncertainty_skill(candidates, state["known_facts"], state.get("missing_fields"))["uncertainty"]
        state["uncertainty"] = uncertainty
        if uncertainty["abstain"]:
            self._finding(state, "uncertainty", "warning", uncertainty["assessment_note"], "证据不足：以追问或弃权收束，不强行给结论。")
        elif uncertainty["separation"] == "narrow":
            self._finding(state, "uncertainty", "warning", uncertainty["assessment_note"])
            if self._queue_tool(state, "evidence_inquiry", "不确定性批判者：top1/top2 区分度不足，回溯挖掘证据以佐证。"):
                self._finding(state, "uncertainty", "info", "已追加 evidence_inquiry 佐证轮。")

        # 4) Completeness critic — question facets not yet covered by any executed tool.
        planned = plan_question(question, max_steps=4)
        for step in planned["hint_plan"]:
            if self._queue_tool(state, step["intent"], f"完整性批判者：问题涉及「{INTENT_BY_ID[step['intent']]['label']}」但尚未执行。"):
                self._finding(state, "completeness", "info", f"补充执行 {step['intent']}。")

        # Decide the next transition.
        if state["tool_plan"] and state["round"] < state["max_rounds"]:
            self._transition(state, "plan", "批判者补充了新工具，进入下一轮重规划。")
            return
        if state["tool_plan"]:
            self._finding(state, "completeness", "info", f"达到轮次上限 {state['max_rounds']}，{len(state['tool_plan'])} 个待执行工具被放弃。")
            state["tool_plan"] = []
        followups = self._followup_questions(state)
        if uncertainty["abstain"] and followups:
            self._transition(state, "ask_followup", "证据不足且存在可澄清缺口：主动追问而非作答。")
        elif uncertainty["abstain"]:
            self._transition(state, "abstain", "证据不足且无明确可澄清缺口：诚实弃权。")
        elif any(c["severity"] == "warning" and c["critic"] == "evidence" for c in state["critic_findings"]) and followups:
            self._transition(state, "ask_followup", "证据冲突未消解：以澄清追问回退，而非平均分数作答。")
        else:
            self._transition(state, "answer", "安全放行、证据可用：汇总作答。")

    def _followup_questions(self, state: dict[str, Any]) -> list[str]:
        questions: list[str] = list(state["risk_state"].get("need_further_inquiry") or [])
        for fact in state["uncertain_facts"]:
            q = f"请确认是否存在：{fact}？"
            if q not in questions:
                questions.append(q)
        for gap in (state.get("uncertainty") or {}).get("differential_gaps") or []:
            if gap.get("suggestion"):
                questions.append(gap["suggestion"])
        for candidate in state["candidate_decisions"][:1]:
            for tag in candidate.get("contradicting_evidence") or []:
                questions.append(f"存在与「{candidate['name']}」相反的证据（{tag}），请补充寒热、舌苔与小便颜色以澄清。")
        for field in state.get("missing_fields") or []:
            question = _MISSING_FIELD_QUESTIONS.get(field)
            if question:
                questions.append(question)
        deduped: list[str] = []
        for q in questions:
            if q not in deduped:
                deduped.append(q)
        return deduped[:5]

    # ------------------------------------------------------------------ RESPOND

    def _respond(self, state: dict[str, Any], question: str) -> dict[str, Any]:
        action = state["next_action"]
        followups = self._followup_questions(state)
        if action == "escalate":
            flags = "\n".join(f"- {f.get('message', f.get('term', ''))}" for f in state["risk_state"]["confirmed_red_flags"][:6])
            answer = (
                "⚠️ **检测到需要立即线下排查的危险信号，本轮暂停常规辨证与方药分析。**\n\n"
                f"{flags}\n\n请尽快前往急诊或脊柱专科评估；确认排除危险后可继续问诊。"
            )
        elif action == "ask_followup":
            answer = "为了给出可靠的分析，需要先澄清以下关键信息：\n\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(followups, 1))
        elif action == "abstain":
            answer = "现有信息不足以形成稳定的证候倾向，系统选择**弃权**而非强行给结论。建议补充四诊信息（疼痛性质、寒热、舌象、脉象）后再评估。"
        else:
            parts = [f"### 第{o['round']}轮 · {o['label']}（{o['intent']}）\n{o['answer']}" for o in state["observations"]]
            answer = "\n\n".join(parts) if parts else "未产生可用观察。"
            notes = [f"- [{f['critic']}/{f['severity']}] {f['finding']}" for f in state["critic_findings"]]
            if notes:
                answer += "\n\n---\n\n**批判者反思记录（critic findings）**\n\n" + "\n".join(notes)
        # Escalation is a hard veto: clinical decision content is withheld from the turn.
        decisions = [] if action == "escalate" else state["candidate_decisions"][:4]
        turn = {
            "question": question,
            "blocked": False,
            "goal": state["goal"],
            "answer": answer,
            "next_action": action,
            "rounds_used": state["round"],
            "max_rounds": state["max_rounds"],
            "followup_questions": followups if action in ("ask_followup", "abstain") else [],
            "candidate_decisions": decisions,
            "risk_state": {
                "safety_status": state["risk_state"]["safety_status"],
                "confirmed": [f.get("term") or f.get("id") for f in state["risk_state"]["confirmed_red_flags"]],
                "denied": [f.get("term") for f in state["risk_state"]["denied_red_flags"]],
                "uncertain": [f.get("term") for f in state["risk_state"]["uncertain_red_flags"]],
            },
            "critic_findings": state["critic_findings"],
            "transitions": state["transitions"],
            "subagents_used": list(state["executed_tools"]),
            "used_llm": any(o.get("used_llm") for o in state["observations"]),
            "agent_state": validate(state, AGENT_STATE, "reflective_agent.final"),
            "answer_source": "reflective_state_machine",
            "intent": "reflective_consult",
            "multi_round": state["round"] > 1,
            "disclaimer": _DISCLAIMER,
        }
        return turn

    # ------------------------------------------------------------------ main loop

    def run(self, question: str) -> dict[str, Any]:
        question = (question or "").strip()
        guard = patient_request_guard_skill(question, user_role=self.user_role)
        if guard["blocked"] and self.user_role == "patient":
            return {
                "question": question, "blocked": True, "answer": guard["message"],
                "next_action": "answer", "rounds_used": 0, "followup_questions": [],
                "candidate_decisions": [], "critic_findings": [], "transitions": [],
                "subagents_used": [], "used_llm": False,
                "answer_source": "patient_request_guard", "intent": "safety_block",
                "disclaimer": "患者端不提供最终诊断、完整处方或可执行剂量。",
            }
        state = self._understand(question)
        # Bounded loop: every branch either advances the round counter toward
        # max_rounds or lands in a terminal action.
        while state["next_action"] in {"plan", "execute", "reflect"}:
            if state["next_action"] == "plan":
                self._plan(state, question)
            elif state["next_action"] == "execute":
                self._execute(state, question)
            else:
                self._reflect(state, question)
        return self._respond(state, question)
