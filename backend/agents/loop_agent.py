"""Agentic CDSS loop agent: free question → TaskGraph → skills/tools/subagents → critics.

This module is the code-level counterpart to the next-generation CDSS blueprint. It keeps
Yao-Bi's safety invariants, but makes the clinical agent more autonomous than the older
fixed pipeline:

* each user turn updates a lightweight ``ClinicalExperienceGraph`` (case facts,
  hypotheses, evidence, gaps, decisions) that persists across turns;
* the planner emits a small TaskGraph with explicit task types (skill, subagent,
  graph_update, critic, judge) instead of a single intent or rigid sequence;
* execution delegates to existing, governed ``ConversationSession`` subagents and the
  tool registry, so existing safety gates, role boundaries and deterministic skills stay
  the source of truth;
* critics can trigger another bounded round: missing evidence, close hypotheses,
  contradictions, or a user goal shift produce follow-up tasks rather than a forced
  conclusion;
* the final answer is a clinician-review decision-support package, never an autonomous
  diagnosis or prescription.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from backend.agents.autonomous_agent import plan_question
from backend.agents.conversation import ConversationSession
from backend.agents.critics import contradiction_critic, evidence_critic, policy_critic
from backend.agents.skill_router import INTENT_BY_ID
from backend.runtime.run_context import AgentRun, RunBudget, StopReason
from backend.tools import get_registry

TaskType = Literal["skill", "tool", "subagent", "graph_query", "graph_update", "critic", "judge"]


@dataclass
class AgentTask:
    """One node in a runtime TaskGraph."""

    task_id: str
    task_type: TaskType
    target: str
    input_refs: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    expected_output: str = ""
    stop_if: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "target": self.target,
            "input_refs": list(self.input_refs),
            "depends_on": list(self.depends_on),
            "expected_output": self.expected_output,
            "stop_if": list(self.stop_if),
            "rationale": self.rationale,
        }


class ClinicalExperienceGraph:
    """Small in-memory graph for multi-turn CDSS state.

    It is intentionally simple (dicts + edge list) so it can be serialized in audit logs
    and later swapped for a graph database without changing the agent contract.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.turn_index = 0

    def add_node(self, node_id: str, node_type: str, **attrs: Any) -> dict[str, Any]:
        node = dict(self.nodes.get(node_id) or {"id": node_id, "type": node_type, "first_seen_turn": self.turn_index})
        node.update(attrs)
        node["id"] = node_id
        node["type"] = node_type
        node["last_updated_turn"] = self.turn_index
        self.nodes[node_id] = node
        return node

    def add_edge(self, source: str, relation: str, target: str, **attrs: Any) -> None:
        edge = {"source": source, "relation": relation, "target": target, **attrs}
        if edge not in self.edges:
            self.edges.append(edge)

    def update_from_case_state(self, case_state: dict[str, Any], question: str, state_updates: dict[str, Any] | None) -> None:
        self.turn_index += 1
        turn_id = f"turn:{self.turn_index}"
        self.add_node(turn_id, "turn", question=question, state_updates=state_updates or {})
        for tag in case_state.get("normalized_tags") or []:
            tag_id = f"case_fact:{tag}"
            self.add_node(tag_id, "case_fact", label=tag, polarity="affirmed")
            self.add_edge(turn_id, "updated_by", tag_id)
        red = case_state.get("red_flags") or {}
        if red.get("status"):
            rf_id = f"safety:red_flag:{red.get('status')}"
            self.add_node(rf_id, "decision", label="red_flag_status", status=red.get("status"), positive_items=red.get("positive_items") or [])
            self.add_edge(turn_id, "updated_by", rf_id)

    def add_observation(self, task: AgentTask, observation: dict[str, Any]) -> None:
        task_id = f"task:{self.turn_index}:{task.task_id}"
        self.add_node(task_id, task.task_type, label=task.target, rationale=task.rationale)
        for ev in observation.get("evidence") or []:
            ev_id = f"evidence:{str(ev)[:80]}"
            self.add_node(ev_id, "evidence", label=str(ev))
            self.add_edge(task_id, "supports", ev_id)
        if task.target in INTENT_BY_ID:
            hyp_id = f"hypothesis:{task.target}"
            self.add_node(hyp_id, "hypothesis", label=INTENT_BY_ID[task.target]["label"], source_task=task.task_id)
            self.add_edge(task_id, "derived_from", hyp_id)

    def gaps(self, case_state: dict[str, Any], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        ev = evidence_critic(steps)
        for intent in ev.get("ungrounded_steps") or []:
            findings.append({
                "gap_id": f"evidence_gap:{intent}",
                "kind": "evidence_gap",
                "target": intent,
                "suggestion": f"补充与 {INTENT_BY_ID.get(intent, {}).get('label', intent)} 相关的病例证据或经验队列证据。",
                "expected_information_gain": 0.25,
            })
        contradictions = contradiction_critic(case_state.get("normalized_tags") or [])
        for idx, item in enumerate(contradictions, start=1):
            findings.append({
                "gap_id": f"contradiction:{idx}",
                "kind": "counterevidence_gap",
                "target": item.get("axis"),
                "suggestion": item.get("note"),
                "expected_information_gain": 0.35,
            })
        if len(case_state.get("normalized_tags") or []) < 3:
            findings.append({
                "gap_id": "low_case_detail",
                "kind": "followup_gap",
                "target": "四诊/疼痛特征/下肢神经症状",
                "suggestion": "病例细节不足，优先追问疼痛性质、遇寒热变化、下肢麻木/无力、舌脉和既往影像。",
                "expected_information_gain": 0.4,
            })
        for gap in findings:
            gid = f"gap:{gap['gap_id']}"
            self.add_node(gid, "followup_gap", **gap)
        return findings

    def snapshot(self) -> dict[str, Any]:
        return {"turn_index": self.turn_index, "nodes": list(self.nodes.values()), "edges": list(self.edges)}


class AgenticCDSSLoopAgent:
    """Multi-turn, graph-backed, bounded-loop CDSS agent.

    ``ask`` is the public multi-turn entry. It lets a free-form user request drive the
    plan, executes existing skills/subagents, runs independent critics, and either asks
    targeted follow-up questions or returns a clinician-review package.
    """

    def __init__(
        self,
        case_state: dict[str, Any] | None = None,
        use_llm: bool = False,
        dao_client: Any | None = None,
        user_role: str = "clinician",
        max_rounds: int = 3,
        max_steps_per_round: int = 4,
        imaging_dao_client: Any | None = None,
    ) -> None:
        self.session = ConversationSession(case_state=case_state, use_llm=use_llm, dao_client=dao_client, user_role=user_role, imaging_dao_client=imaging_dao_client)
        self.use_llm = use_llm
        self.dao_client = dao_client
        self.imaging_dao_client = imaging_dao_client or dao_client
        self.user_role = user_role
        self.max_rounds = max_rounds
        self.max_steps_per_round = max_steps_per_round
        self.graph = ClinicalExperienceGraph()
        self.history: list[dict[str, Any]] = []

    @property
    def case_state(self) -> dict[str, Any]:
        return self.session.case_state

    def _plan_task_graph(self, question: str, round_no: int, gaps: list[dict[str, Any]] | None = None) -> list[AgentTask]:
        if gaps:
            tasks = [
                AgentTask(
                    task_id=f"r{round_no}_followup_strategy",
                    task_type="subagent",
                    target="red_flag_inquiry" if self._has_unresolved_red_flag() else "reasoning_inquiry",
                    input_refs=[g["gap_id"] for g in gaps[:3]],
                    expected_output="gap-bound follow-up strategy",
                    rationale="Critic 发现信息缺口，进入自主追问/复核轮。",
                ),
                AgentTask(
                    task_id=f"r{round_no}_judge",
                    task_type="judge",
                    target="JudgeAgent",
                    depends_on=[f"r{round_no}_followup_strategy"],
                    expected_output="loop decision",
                    rationale="根据缺口价值决定追问、补检索或输出候选决策包。",
                ),
            ]
            return tasks

        planned = plan_question(question, max_steps=self.max_steps_per_round, use_llm=self.use_llm, dao_client=self.dao_client)
        tasks: list[AgentTask] = [
            AgentTask(
                task_id=f"r{round_no}_graph_update",
                task_type="graph_update",
                target="ClinicalExperienceGraph.update_from_case_state",
                expected_output="updated case graph",
                rationale="先把本轮自由叙述写入病例/经验/决策图谱。",
            )
        ]
        for idx, step in enumerate(planned["plan"], start=1):
            tasks.append(AgentTask(
                task_id=f"r{round_no}_subagent_{idx}",
                task_type="subagent",
                target=step["intent"],
                depends_on=[f"r{round_no}_graph_update"],
                expected_output=INTENT_BY_ID.get(step["intent"], {}).get("description", "subagent observation"),
                stop_if=["safety_halt", "policy_denied"],
                rationale=step.get("reason", "模型/规则 planner 选择该 skill。"),
            ))
        tasks.append(AgentTask(
            task_id=f"r{round_no}_critic",
            task_type="critic",
            target="CriticAgent",
            depends_on=[t.task_id for t in tasks if t.task_type == "subagent"],
            expected_output="safety/evidence/contradiction/role critique",
            rationale="执行后主动找证据缺口、反证、角色越界和过度确定。",
        ))
        tasks.append(AgentTask(
            task_id=f"r{round_no}_judge",
            task_type="judge",
            target="JudgeAgent",
            depends_on=[f"r{round_no}_critic"],
            expected_output="continue | ask_followup | ready_for_clinician | safety_halt | abstain",
            rationale="综合本轮观察和批判结果，决定是否继续 loop。",
        ))
        return tasks

    def _has_unresolved_red_flag(self) -> bool:
        return (self.case_state.get("red_flags") or {}).get("status") == "urgent"

    def _execute_task(self, task: AgentTask, question: str, state_updates: dict[str, Any] | None, steps: list[dict[str, Any]]) -> dict[str, Any]:
        if task.task_type == "graph_update":
            self.graph.update_from_case_state(self.case_state, question, state_updates)
            return {"status": "ok", "answer": "病例图谱已更新。", "evidence": [], "skills": ["ClinicalExperienceGraph"]}
        if task.task_type == "subagent":
            obs = self.session.invoke(task.target, question)
            step = {
                "task_id": task.task_id,
                "intent": obs["intent"],
                "label": obs["label"],
                "answer": obs["answer"],
                "skills": obs.get("skills", []),
                "evidence": obs.get("evidence", []),
                "used_llm": obs.get("used_llm", False),
                "rationale": task.rationale,
            }
            steps.append(step)
            self.graph.add_observation(task, step)
            return {"status": "ok", **step}
        if task.task_type == "tool":
            res = get_registry().invoke(task.target, {}, role="system")
            return {"status": res["status"], "answer": str(res.get("output") or res.get("error") or ""), "evidence": [], "skills": [task.target]}
        if task.task_type == "critic":
            critique = self._critique(steps)
            return {"status": "ok", "answer": "critique complete", "critique": critique, "evidence": [], "skills": ["CriticAgent"]}
        if task.task_type == "judge":
            critique = self._critique(steps)
            decision = self._judge(critique)
            return {"status": "ok", "answer": decision["state"], "decision": decision, "evidence": [], "skills": ["JudgeAgent"]}
        return {"status": "skipped", "answer": f"unsupported task type: {task.task_type}", "evidence": [], "skills": []}

    def _critique(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        gaps = self.graph.gaps(self.case_state, steps)
        return {
            "policy": policy_critic(self.user_role, steps),
            "evidence": evidence_critic(steps),
            "contradictions": contradiction_critic(self.case_state.get("normalized_tags") or []),
            "gaps": gaps,
        }

    def _judge(self, critique: dict[str, Any]) -> dict[str, Any]:
        if self._has_unresolved_red_flag():
            state = "safety_halt"
            reason = "红旗危险信号未排除，停止辨证/方药 loop。"
        elif not critique.get("policy", {}).get("ok", True):
            state = "abstain"
            reason = "角色边界 critic 发现患者端临床输出风险。"
        elif critique.get("gaps") and any(g.get("expected_information_gain", 0) >= 0.35 for g in critique["gaps"]):
            state = "ask_followup"
            reason = "仍存在高价值信息缺口，优先自主追问而非强行结论。"
        elif critique.get("evidence", {}).get("grounded_steps", 0) == 0:
            state = "abstain"
            reason = "没有足够接地证据支撑候选诊疗框架。"
        else:
            state = "ready_for_clinician"
            reason = "安全未中止，主要子任务已有证据，可输出医师复核决策包。"
        return {"state": state, "reason": reason, "next_tasks": [], "confidence_summary": {"grounded_steps": critique.get("evidence", {}).get("grounded_steps", 0)}}

    @staticmethod
    def _followup_questions(gaps: list[dict[str, Any]], max_questions: int = 3) -> list[dict[str, Any]]:
        questions: list[dict[str, Any]] = []
        for gap in sorted(gaps, key=lambda g: g.get("expected_information_gain", 0), reverse=True)[:max_questions]:
            target = gap.get("target") or "关键症状"
            if gap["kind"] == "counterevidence_gap":
                text = f"为了区分冲突线索，请补充：{target} 相关症状出现的先后、轻重和当前是否仍存在？"
            elif gap["kind"] == "evidence_gap":
                text = f"关于 {INTENT_BY_ID.get(target, {}).get('label', target)}，请补充最能支持或反驳该判断的症状、舌脉、影像或既往治疗反应。"
            else:
                text = "请补充疼痛性质、遇寒热变化、下肢麻木/无力、舌脉、既往影像和当前用药。"
            questions.append({
                "question_text": text,
                "target_gap": gap["gap_id"],
                "expected_information_gain": gap.get("expected_information_gain", 0),
                "what_answer_would_change": gap.get("suggestion", "可改变候选证型/方路排序或安全分级。"),
                "patient_friendly_reason": "这些信息有助于医生判断是否需要先排除风险，以及哪些候选方向更值得复核。",
            })
        return questions

    def _synthesize(self, question: str, steps: list[dict[str, Any]], critique: dict[str, Any], decision: dict[str, Any]) -> str:
        if decision["state"] == "safety_halt":
            safety = next((s for s in steps if s.get("intent") == "red_flag_inquiry"), None)
            return (safety or {}).get("answer") or "红旗危险信号未排除，请先线下/急诊评估。"
        lines = [
            "## 自主智能体决策支持包（医师复核草案）",
            f"**Loop 决策**：{decision['state']} — {decision['reason']}",
        ]
        if steps:
            lines.append("\n### 已调用的 skill / subagent")
            for step in steps:
                lines.append(f"- **{step['label']}**：{step['answer'].splitlines()[0][:160]}")
        gaps = critique.get("gaps") or []
        if gaps:
            lines.append("\n### Critic 发现的缺口/反证")
            for gap in gaps[:5]:
                lines.append(f"- `{gap['gap_id']}`：{gap.get('suggestion')}")
        if decision["state"] == "ask_followup":
            lines.append("\n### 下一轮自主问诊建议")
            for q in self._followup_questions(gaps):
                lines.append(f"- {q['question_text']}（目标：{q['target_gap']}）")
        lines.append("\n> 以上为 CDSS 候选决策支持，不构成最终诊断、处方或患者自服方案；需执业医师结合查体、影像和用药史终审。")
        return "\n".join(lines)

    def ask(self, question: str) -> dict[str, Any]:
        run = AgentRun(goal=question, user_role=self.user_role, budget=RunBudget(max_iterations=self.max_rounds * (self.max_steps_per_round + 3)))
        run.start()
        state_updates = self.session.absorb_question_facts(question)
        rounds: list[dict[str, Any]] = []
        all_steps: list[dict[str, Any]] = []
        critique: dict[str, Any] = {}
        decision: dict[str, Any] = {"state": "continue", "reason": "not started"}
        gaps: list[dict[str, Any]] | None = None

        for round_no in range(1, self.max_rounds + 1):
            exhausted = run.budget.charge("iteration")
            if exhausted is not None:
                decision = {"state": "budget_exhausted", "reason": exhausted.value, "next_tasks": []}
                break
            tasks = self._plan_task_graph(question, round_no, gaps)
            observations: list[dict[str, Any]] = []
            round_steps: list[dict[str, Any]] = []
            for task in tasks:
                obs = self._execute_task(task, question, state_updates, round_steps)
                observations.append({"task": task.to_dict(), "observation": obs})
                if task.task_type == "critic":
                    critique = obs["critique"]
                if task.task_type == "judge":
                    decision = obs["decision"]
            all_steps.extend(round_steps)
            rounds.append({"round": round_no, "tasks": [t.to_dict() for t in tasks], "observations": observations, "decision": decision})
            if decision["state"] in {"ready_for_clinician", "safety_halt", "abstain", "budget_exhausted"}:
                break
            if decision["state"] == "ask_followup":
                gaps = critique.get("gaps") or []
                # Stop after producing concrete follow-up questions; the next user turn
                # continues the loop with new information in the same graph/session.
                break

        stop_map = {
            "ready_for_clinician": StopReason.GOAL_COMPLETED,
            "safety_halt": StopReason.SAFETY_HALT,
            "budget_exhausted": StopReason.BUDGET_EXHAUSTED,
            "abstain": StopReason.INSUFFICIENT_EVIDENCE,
            "ask_followup": StopReason.HUMAN_INPUT_REQUIRED,
        }
        run.finish(stop_map.get(decision.get("state"), StopReason.GOAL_COMPLETED), note=decision.get("reason"))
        followups = self._followup_questions((critique or {}).get("gaps") or []) if decision.get("state") == "ask_followup" else []
        turn = {
            "question": question,
            "answer": self._synthesize(question, all_steps, critique, decision),
            "rounds": rounds,
            "steps": all_steps,
            "decision": decision,
            "critic": critique,
            "followup_questions": followups,
            "graph": self.graph.snapshot(),
            "case_state": self.case_state,
            "run": run.to_dict(),
            "used_llm": any(s.get("used_llm") for s in all_steps),
            "agentic": True,
            "disclaimer": "多轮自主智能体仅输出候选 CDSS 决策支持，最终诊疗由执业医师负责。",
        }
        self.history.append(turn)
        return turn
