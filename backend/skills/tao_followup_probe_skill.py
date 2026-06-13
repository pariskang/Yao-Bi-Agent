from __future__ import annotations

from typing import Any

from backend.llm.dao_client import DaoClient, DaoRuntimeError
from backend.llm.json_repair import JsonRepairError, loads_with_repair
from backend.llm.output_guard import guard_tao_output

# 各状态的临床主题（约束 Tao 追问只能停留在本状态主题内）。
STATE_THEME = {
    "S3_PAIN_PROFILE": "疼痛部位、性质、程度、诱因与缓解因素",
    "S4_NEURO_ORTHO": "下肢放射痛、麻木、无力、行走与影像/既往诊断",
    "S5_TCM_CORE": "中医寒热、湿象、气血、舌象脉象等四诊信息",
    "S6_SHEN_SIGNAL": "沈老经验相关的寒湿、通络、肝肾、少阳枢机线索",
    "S7_COMORBIDITY": "合并疾病、止痛/消炎/抗凝/激素用药与过敏史",
    "S8_ADAPTIVE_REPAIR": "尚未补齐的高价值医案字段",
}

# 允许 Tao 自动追问的状态：红旗硬门控、知情、基础人口学不开放生成式追问。
PROBE_ENABLED_STATES = set(STATE_THEME)


def tao_followup_probe_skill(
    case_state: dict[str, Any],
    state: str,
    allowed_fields: list[str],
    rule_context: dict[str, Any] | None = None,
    last_answers: dict[str, Any] | None = None,
    max_probes: int = 2,
    dao_client: DaoClient | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Let Tao generate bounded, rule-constrained follow-up probes.

    与 ``tao_question_planner_skill``（只能重排/改写既有规则问题）不同，本技能允许 Tao
    在“当前状态临床主题”内**生成新的澄清式追问**，但施加硬约束：

    * 只在 clinical-content 状态启用（红旗筛查/知情/基础人口学不开放生成式追问）；
    * 每轮最多 ``max_probes`` 个追问，且不驱动状态跳转（仅作为补充线索）；
    * ``field_hint`` 必须取自 ``allowed_fields`` 或为 null；
    * 输出经 JSON 修复与 ``guard_tao_output`` 校验，出现诊断/处方/剂量即整轮作废回退。
    """

    meta: dict[str, Any] = {
        "enabled": use_llm,
        "status": "not_requested" if not use_llm else "pending",
        "fallback_used": True,
        "guard": None,
        "json_repair": None,
        "backend": getattr(getattr(dao_client, "config", None), "backend", None),
        "rule_constrained": True,
    }
    if not use_llm or max_probes <= 0 or state not in PROBE_ENABLED_STATES:
        meta["status"] = "not_applicable" if state not in PROBE_ENABLED_STATES else meta["status"]
        return {"probes": [], "tao_probe_runtime": meta}

    allowed = list(allowed_fields or [])
    payload = {
        "task": "caseguide_followup_probe",
        "state": state,
        "current_state_theme": STATE_THEME.get(state, "本状态主题"),
        "allowed_fields": allowed,
        "last_answers": last_answers or {},
        "rule_context": rule_context or {},
        "normalized_tags": sorted(set(case_state.get("normalized_tags") or [])),
        "max_probes": max_probes,
        "output_contract": {
            "format": "json_object",
            "allowed_field_hints": allowed + [None],
            "forbidden_actions": ["final_diagnosis", "syndrome_verdict", "complete_prescription", "dose_instruction", "out_of_theme_question"],
        },
    }
    client = dao_client or DaoClient()
    meta["backend"] = client.config.backend
    try:
        raw = client.generate_followup_probes(payload)
        parsed, repair_meta = loads_with_repair(raw)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("probes"), list):
            raise JsonRepairError("Tao probe output must be an object with a probes list.")
        allowed_set = set(allowed)
        probes: list[dict[str, Any]] = []
        guard_text_parts: list[str] = []
        for index, item in enumerate(parsed["probes"]):
            if not isinstance(item, dict):
                continue
            probe_text = str(item.get("probe_text") or "").strip()
            if not probe_text:
                continue
            field_hint = item.get("field_hint")
            if field_hint is not None and field_hint not in allowed_set:
                # 越界 field_hint 不直接采纳为结构化字段，降级为纯文字线索。
                field_hint = None
            reason = str(item.get("reason") or "").strip()
            guard_text_parts.extend([probe_text, reason])
            probes.append({
                "id": f"TAO_PROBE_{state}_{index + 1}",
                "question": probe_text,
                "field_hint": field_hint,
                "reason": reason or "Tao在本状态主题内的澄清式追问（待医师复核）。",
                "source": "tao_probe",
                "rule_constrained": True,
                "state": state,
                "input_type": "free_text",
                "advisory_only": True,
            })
        guard = guard_tao_output("\n".join(guard_text_parts), parsed)
        meta.update({"json_repair": repair_meta, "guard": guard, "status": "accepted" if guard["allowed"] and probes else "guard_rejected"})
        if not guard["allowed"] or not probes:
            return {"probes": [], "tao_probe_runtime": meta}
        meta["fallback_used"] = False
        return {"probes": probes[:max_probes], "tao_probe_runtime": meta}
    except (DaoRuntimeError, JsonRepairError, ValueError, KeyError, TypeError) as exc:
        meta.update({"status": "fallback", "error": str(exc), "fallback_used": True})
        return {"probes": [], "tao_probe_runtime": meta}
