"""Primitives for the YaoBi multi-agent collaboration layer.

设计目标：把原本"顺序调用 skill"的隐式编排，显式化为"多个智能体在共享黑板上自主协作"：

* ``Blackboard`` 是共享工作记忆（短期记忆 + 消息传递的载体）；上游智能体写入结论，
  下游智能体读取并续接，形成自主接力。
* ``AgentResult`` 是每个智能体的标准产出：状态、置信度、证据、是否调用语言模型、
  语言模型运行时与守卫状态、以及把接力棒交给哪些智能体（handoff）。
* ``AgentMessage`` 是协作轨迹中的一条记录，用于审计与 UI 时间轴可视化。

安全不变量：红旗智能体可自主"中止"下游临床智能体；语言模型智能体的输出必须经
JSON 修复 + 输出守卫；任何智能体都不得越权产出最终诊断 / 处方 / 可执行剂量。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Blackboard:
    """Shared working memory the agents read from and write to."""

    case_state: dict[str, Any]
    use_llm: bool = False
    dao_client: Any | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    halted: bool = False
    halt_reason: str | None = None

    def put(self, key: str, value: Any) -> None:
        self.outputs[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.outputs.get(key, default)


@dataclass
class AgentResult:
    """Standard output every agent returns to the orchestrator."""

    name: str
    role: str
    kind: str  # "rule" | "llm" | "hybrid"
    status: str  # ok | escalate | halt | blocked | skipped
    summary: str
    confidence: float | None = None
    used_llm: bool = False
    evidence: list[Any] = field(default_factory=list)
    handoff_to: list[str] = field(default_factory=list)
    llm_runtime: dict[str, Any] | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    halt_pipeline: bool = False

    def to_message(self, step: int) -> dict[str, Any]:
        return {
            "step": step,
            "agent": self.name,
            "role": self.role,
            "kind": self.kind,
            "status": self.status,
            "summary": self.summary,
            "confidence": self.confidence,
            "used_llm": self.used_llm,
            "evidence": self.evidence[:8],
            "handoff_to": self.handoff_to,
            "llm_runtime": self._compact_runtime(),
        }

    def _compact_runtime(self) -> dict[str, Any] | None:
        if not self.llm_runtime:
            return None
        guard = self.llm_runtime.get("guard") or {}
        return {
            "enabled": self.llm_runtime.get("enabled"),
            "status": self.llm_runtime.get("status"),
            "fallback_used": self.llm_runtime.get("fallback_used"),
            "guard_allowed": guard.get("allowed") if guard else None,
            "backend": self.llm_runtime.get("backend"),
        }
