"""Autonomous multi-step QA agent (Plan → delegate to subagents → synthesize).

This upgrades the single-intent conversational router into a frontier-style agent:

* **Plan** — decompose a question into an ordered plan of skill calls. Deterministic
  keyword planning is always available; an optional, guarded language-model planner may
  reorder/expand the plan but only with intents from the registered allowlist.
* **Delegate to subagents** — each plan step is delegated to the subagent that owns that
  intent (``ConversationSession.invoke``), so one question can autonomously call several
  skills, with later steps able to build on earlier observations.
* **Synthesize** — combine the per-subagent observations into one answer and emit a
  ReAct-style trace (thought → action → observation) for audit and UI.

Safety invariants are unchanged: subagents only run registered skills over deterministic
rules / de-identified mined data; patient requests for diagnosis/prescription/dose are
blocked; the language model only selects/sequences skills, never invents clinical content.
"""

from __future__ import annotations

from typing import Any

from backend.agents.conversation import ConversationSession
from backend.agents.skill_router import ALLOWED_INTENTS, INTENT_BY_ID, INTENTS, keyword_route
from backend.llm.dao_client import DaoClient, DaoRuntimeError
from backend.llm.json_repair import JsonRepairError, loads_with_repair
from backend.skills.patient_request_guard_skill import patient_request_guard_skill


def plan_question(
    question: str,
    max_steps: int = 3,
    use_llm: bool = False,
    dao_client: DaoClient | None = None,
) -> dict[str, Any]:
    """Decompose a question into an ordered, deduplicated plan of skill intents."""

    text = (question or "").lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in INTENTS:
        if item["intent"] == "capabilities":
            continue
        hits = [kw for kw in item["keywords"] if kw.lower() in text]
        if hits:
            scored.append((len(hits), {"intent": item["intent"], "reason": f"问题包含「{'、'.join(hits[:3])}」线索，需要{item['label']}。"}))
    scored.sort(key=lambda x: x[0], reverse=True)
    hint_plan = [step for _, step in scored[:max_steps]]
    if not hint_plan:
        intent = keyword_route(question)[0]
        hint_plan = [{"intent": intent, "reason": f"按默认路由调用{INTENT_BY_ID.get(intent, {}).get('label', intent)}。"}]

    method = "keyword"
    plan = hint_plan
    runtime: dict[str, Any] = {"enabled": use_llm, "status": "not_requested" if not use_llm else "pending", "fallback_used": True, "backend": getattr(getattr(dao_client, "config", None), "backend", None)}

    if use_llm:
        client = dao_client or DaoClient()
        runtime["backend"] = client.config.backend
        payload = {
            "question": question,
            "allowed_intents": ALLOWED_INTENTS,
            "intent_catalog": [{"intent": i["intent"], "label": i["label"], "description": i["description"]} for i in INTENTS],
            "hint_plan": hint_plan,
            "max_steps": max_steps,
        }
        try:
            raw = client.plan_skills(payload)
            parsed, repair_meta = loads_with_repair(raw)
            runtime["json_repair"] = repair_meta
            steps = parsed.get("plan") if isinstance(parsed, dict) else None
            cleaned: list[dict[str, Any]] = []
            seen: set[str] = set()
            for step in steps or []:
                intent = step.get("intent") if isinstance(step, dict) else None
                if intent in INTENT_BY_ID and intent not in seen:
                    seen.add(intent)
                    cleaned.append({"intent": intent, "reason": str(step.get("reason", ""))[:160] or INTENT_BY_ID[intent]["description"]})
            if cleaned:
                plan, method = cleaned[:max_steps], "llm"
                runtime.update({"status": "accepted", "fallback_used": False})
            else:
                runtime.update({"status": "fallback", "error": "no valid intents in plan"})
        except (DaoRuntimeError, JsonRepairError, ValueError, KeyError, TypeError) as exc:
            runtime.update({"status": "fallback", "error": str(exc)})

    return {"plan": plan, "method": method, "hint_plan": hint_plan, "llm_runtime": runtime}


class AutonomousQAAgent:
    """A planning agent that delegates each step to a skill subagent."""

    def __init__(self, case_state: dict[str, Any] | None = None, use_llm: bool = False, dao_client: DaoClient | None = None, user_role: str = "clinician", max_steps: int = 3) -> None:
        self.session = ConversationSession(case_state=case_state, use_llm=use_llm, dao_client=dao_client, user_role=user_role)
        self.use_llm = use_llm
        self.dao_client = dao_client
        self.user_role = user_role
        self.max_steps = max_steps
        self.history: list[dict[str, Any]] = []

    def run(self, question: str) -> dict[str, Any]:
        guard = patient_request_guard_skill(question, user_role=self.user_role)
        if guard["blocked"] and self.user_role == "patient":
            turn = {
                "question": question, "blocked": True, "plan": [], "plan_method": "patient_request_guard",
                "steps": [], "subagents_used": [], "used_llm": False,
                "answer": guard["message"], "trace": [{"step": 1, "thought": "检测到最终诊断/处方/剂量请求，安全护栏拦截。", "action": "patient_request_guard", "observation": guard["message"]}],
                "disclaimer": "患者端不提供最终诊断、完整处方或可执行剂量。",
            }
            self.history.append(turn)
            return turn

        planned = plan_question(question, max_steps=self.max_steps, use_llm=self.use_llm, dao_client=self.dao_client)
        plan = planned["plan"]
        steps: list[dict[str, Any]] = []
        trace: list[dict[str, Any]] = []
        subagents: list[str] = []
        used_llm = False
        for i, step in enumerate(plan, start=1):
            intent = step["intent"]
            observation = self.session.invoke(intent, question)
            subagents.append(intent)
            used_llm = used_llm or observation["used_llm"]
            steps.append({"step": i, "intent": intent, "label": observation["label"], "reason": step.get("reason", ""), "answer": observation["answer"], "skills": observation["skills"], "evidence": observation["evidence"], "used_llm": observation["used_llm"]})
            trace.append({"step": i, "thought": step.get("reason", ""), "action": f"delegate→{observation['label']}({intent})", "observation": observation["answer"], "skills": observation["skills"]})

        answer = self._synthesize(question, planned, steps)
        turn = {
            "question": question, "blocked": False,
            "plan": [{"intent": s["intent"], "label": INTENT_BY_ID.get(s["intent"], {}).get("label", s["intent"]), "reason": s.get("reason", "")} for s in plan],
            "plan_method": planned["method"], "plan_runtime": planned["llm_runtime"],
            "steps": steps, "trace": trace, "subagents_used": subagents,
            "multi_step": len(steps) > 1, "used_llm": used_llm, "answer": answer,
            "disclaimer": "自主智能体仅规划与调用受限技能，回答基于确定性规则与脱敏数据；不构成最终诊断、处方或可执行剂量。",
        }
        self.history.append(turn)
        return turn

    def _synthesize(self, question: str, planned: dict[str, Any], steps: list[dict[str, Any]]) -> str:
        if not steps:
            return "未能形成执行计划，请换一种问法或参考功能引导。"
        if len(steps) == 1:
            return steps[0]["answer"]
        plan_line = "为回答此问题，自主规划了 " + str(len(steps)) + " 步并委派给对应子智能体：" + " → ".join(s["label"] for s in steps) + "。"
        body = "\n\n".join(f"### {s['step']}. {s['label']}（{s['intent']}）\n{s['answer']}" for s in steps)
        return f"{plan_line}\n\n{body}"

    def starters(self) -> list[dict[str, Any]]:
        return self.session.starters()
