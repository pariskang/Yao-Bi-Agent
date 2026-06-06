from __future__ import annotations

from typing import Any


def clinician_handoff_skill(case_state: dict[str, Any], formula_routes: list[dict[str, Any]] | None = None, matched_modules: list[dict[str, Any]] | None = None, safety: dict[str, Any] | None = None) -> dict[str, str]:
    chief = case_state.get("chief_complaint", {}).get("standard_text") or case_state.get("chief_complaint", {}).get("main_symptom") or "腰痛待整理"
    tags = set(case_state.get("normalized_tags") or [])
    main_problems = [chief]
    if "lower_limb_numbness" in tags:
        main_problems.append("伴下肢麻木/感觉异常线索")
    if {"cold_aggravation", "warmth_relieves"} & tags or "cold_aversion" in tags:
        main_problems.append("伴寒象或热敷缓解线索")
    if "osteoporosis" in tags:
        main_problems.append("既往/疑似骨质疏松背景")
    priorities = ["神经根受压程度", "椎管狭窄", "骨质疏松性压缩骨折", "进行性肌力下降"]
    if safety and safety.get("safety_status") in {"urgent", "caution"}:
        priorities.insert(0, "已命中红旗/可疑风险，需优先线下评估")
    rule_clues = []
    signals = case_state.get("shen_rule_signals", {})
    if signals.get("qixue_bizhu_damp_signal") or {"dark_tongue", "white_greasy_coating"} & tags:
        rule_clues.append("气血痹阻夹湿")
    if signals.get("bushen_bone_signal"):
        rule_clues.append("肝肾不足背景")
    if signals.get("cold_damp_signal") or "cold_aversion" in tags:
        rule_clues.append("寒凝经脉/寒湿线索")
    if signals.get("danggui_sini_signal"):
        rule_clues.append("下肢麻木通络信号")
    modules = [m.get("name") for m in matched_modules or []][:6]
    routes = [r.get("name") for r in formula_routes or []][:3]
    missing = case_state.get("missing_fields") or []
    markdown = f"""# 医生复核摘要

## 1. 主要问题
{chr(10).join(f'- {item}' for item in main_problems)}

## 2. 需优先排除
{chr(10).join(f'- {item}' for item in priorities)}

## 3. 中医规则线索（待医生复核）
{chr(10).join(f'- {item}' for item in rule_clues) or '- 信息不足，暂未形成稳定线索'}

## 4. 沈老经验可能相关模块/路线（非处方）
{chr(10).join(f'- {item}' for item in (modules + routes)) or '- 暂未命中'}

## 5. 信息缺口
{chr(10).join(f'- {item}' for item in missing[:10]) or '- 暂无关键缺口'}

> 以上为医案整理线索，不是最终诊断或处方。
"""
    return {"clinician_handoff_markdown": markdown}
