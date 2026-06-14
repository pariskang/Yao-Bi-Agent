"""AgentOrchestrator — coordinates autonomous agent collaboration over a shared blackboard.

The orchestrator makes the collaboration mechanism explicit and auditable:

* agents run in dependency order, each reading upstream outputs and writing its own
  onto the shared :class:`Blackboard` (shared working memory / message passing);
* an agent may take an autonomous control decision — the red-flag agent can *halt*
  the pipeline, after which only ``runs_after_halt`` agents (the emergency notice)
  execute and the rest are recorded as skipped;
* each step is captured in a ``collaboration_trace`` that records role, rule-vs-LLM,
  confidence, evidence, language-model runtime/guard status, and explicit handoffs.

The orchestrator never re-implements clinical logic: every agent wraps a tested skill,
so the deterministic outputs remain the source of truth and language-model output stays
guarded and optional.
"""

from __future__ import annotations

from typing import Any

from backend.agents.base import AgentResult, Blackboard
from backend.agents.clinical_agents import DEFAULT_AGENTS, EMERGENCY_AGENT


class AgentOrchestrator:
    def __init__(self, agents: list[Any] | None = None, emergency_agent: Any | None = None) -> None:
        self.agents = agents if agents is not None else DEFAULT_AGENTS
        self.emergency_agent = emergency_agent if emergency_agent is not None else EMERGENCY_AGENT

    def describe(self) -> list[dict[str, Any]]:
        """Static description of the agent graph (roster + handoffs) for UI/docs."""

        roster = [{"name": a.name, "role": a.role, "kind": a.kind, "handoff_to": list(getattr(a, "handoff_to", []))} for a in self.agents]
        roster.append({"name": self.emergency_agent.name, "role": self.emergency_agent.role, "kind": self.emergency_agent.kind, "handoff_to": list(self.emergency_agent.handoff_to), "trigger": "red_flag_halt"})
        return roster

    def run(self, case_state: dict[str, Any], use_llm: bool = False, dao_client: Any | None = None) -> dict[str, Any]:
        bb = Blackboard(case_state=case_state, use_llm=use_llm, dao_client=dao_client)
        trace: list[dict[str, Any]] = []
        results: list[AgentResult] = []
        step = 0

        for agent in self.agents:
            if bb.halted and not getattr(agent, "runs_after_halt", False):
                step += 1
                trace.append({
                    "step": step, "agent": agent.name, "role": agent.role, "kind": agent.kind,
                    "status": "skipped", "summary": f"上游红旗中止，跳过（{bb.halt_reason}）。",
                    "confidence": None, "used_llm": False, "evidence": [],
                    "handoff_to": list(getattr(agent, "handoff_to", [])), "llm_runtime": None,
                })
                continue
            result = agent.run(bb)
            step += 1
            trace.append(result.to_message(step))
            results.append(result)
            bb.case_state = bb.case_state  # case_state may have been replaced in-place by agents
            if result.halt_pipeline:
                bb.halted = True
                bb.halt_reason = result.summary

        if bb.halted:
            emergency = self.emergency_agent.run(bb)
            step += 1
            trace.append(emergency.to_message(step))
            results.append(emergency)

        used_llm_agents = [r.name for r in results if r.used_llm]
        return {
            "collaboration_trace": trace,
            "agent_roster": self.describe(),
            "halted": bb.halted,
            "halt_reason": bb.halt_reason,
            "used_llm_agents": used_llm_agents,
            "llm_in_loop": bool(used_llm_agents),
            "blackboard": bb.outputs,
            "case_state": bb.case_state,
            "agent_count": len(results),
        }
