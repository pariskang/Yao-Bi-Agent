from __future__ import annotations

from typing import Any


def _join(items: Any, default: str = "未详") -> str:
    if isinstance(items, list):
        return "、".join(str(item) for item in items if item) or default
    return str(items) if items not in [None, "", []] else default


def case_structuring_skill(case_state: dict[str, Any]) -> dict[str, Any]:
    profile = case_state.get("patient_profile", {})
    chief = case_state.get("chief_complaint", {})
    pain = case_state.get("pain_profile", {})
    neuro = case_state.get("neuro_ortho", {})
    tcm = case_state.get("tcm_inquiry", {})
    comorb = case_state.get("comorbidity", {})
    red = case_state.get("red_flags", {})
    chief_text = chief.get("standard_text") or chief.get("main_symptom") or "腰痛待整理"
    history = (
        f"患者诉{chief_text}。疼痛部位：{_join(pain.get('location'))}；"
        f"放射情况：{_join(pain.get('radiation'))}；疼痛性质：{_join(pain.get('pain_nature'))}；"
        f"疼痛评分：{_join(pain.get('severity_0_10'))}/10。"
        f"加重因素：{_join(pain.get('aggravating_factors'))}；缓解因素：{_join(pain.get('relieving_factors'))}。"
        f"下肢麻木：{_join(neuro.get('numbness'))}，部位：{_join(neuro.get('numbness_location'))}；"
        f"下肢无力：{_join(neuro.get('weakness'))}。"
    )
    shen_lines = []
    signals = case_state.get("shen_rule_signals", {})
    signal_text = {
        "bushen_bone_signal": "年龄/久病/骨质疏松 → 补肝肾强筋骨规则线索。",
        "danggui_sini_signal": "下肢麻木或放射痛 → 当归四逆汤/通草细辛通络路线信号。",
        "qixue_bizhu_damp_signal": "舌暗、苔腻、久痛 → 气血痹阻夹湿信号。",
        "cold_damp_signal": "遇冷加重、热敷缓解 → 寒湿/温经散寒信号。",
        "chaihu_signal": "口苦口干、睡眠差或压力大 → 柴胡类方/少阳线索。",
        "stomach_protection_signal": "胃纳差或服药胃不适 → 顾护中焦信号。",
    }
    for key, text in signal_text.items():
        if signals.get(key):
            shen_lines.append(text)
    missing = case_state.get("missing_fields") or []
    markdown = f"""# 腰痹医案草稿

## 一、基本信息
患者：{_join(profile.get('sex'))}，{_join(profile.get('age'))}岁  
职业/体力负荷：{_join(profile.get('occupation'))} / {_join(profile.get('physical_labor'))}  
就诊目的：腰腿痛医案整理，供医生复核。  

## 二、主诉
{chief_text}。

## 三、现病史
{history}
红旗筛查状态：{_join(red.get('status'))}；阳性/可疑项目：{_join(red.get('positive_items'))}。

## 四、伴随症状
寒热：{_join(tcm.get('cold_heat'))}；寒热与疼痛关系：{_join(tcm.get('cold_pain_relation'))}。  
湿重/困重：{_join(tcm.get('dampness'))}；乏力：{_join(tcm.get('fatigue'))}。  
睡眠：{_join(tcm.get('sleep'))}；胃纳：{_join(tcm.get('appetite'))}；口苦口干：{_join(tcm.get('mouth_taste'))}。  
二便：大便{_join(tcm.get('stool'))}，小便{_join(tcm.get('urine'))}。  

## 五、既往史与检查
既往疾病：{_join(comorb.get('diseases'))}。  
影像/检查：{_join(neuro.get('imaging'))}；既往诊断：{_join(neuro.get('western_diagnosis'))}。  
近期用药：{_join(comorb.get('medications'))}；过敏史：{_join(comorb.get('allergy'))}。  

## 六、中医四诊信息
舌象：舌色{_join(tcm.get('tongue', {}).get('color'))}，舌苔{_join(tcm.get('tongue', {}).get('coating'))}。  
脉象：{_join(tcm.get('pulse'), '患者未提供，待医生面诊补充')}。  

## 七、结构化标签
{chr(10).join(f'- {tag}' for tag in case_state.get('normalized_tags', [])) or '- 暂无'}

## 八、沈老经验规则线索
{chr(10).join(f'{idx + 1}. {line}' for idx, line in enumerate(shen_lines)) or '1. 暂未形成稳定规则线索，需补充信息。'}

## 九、待医生补充
{chr(10).join(f'- {field}' for field in missing[:12]) or '- 暂无关键缺口'}

> 本医案草稿仅用于整理沟通、科研标注和医生复核，不构成诊断、处方或治疗建议。
"""
    return {"standard_case_markdown": markdown, "patient_brief": _patient_brief(case_state), "clinician_case": _clinician_case(case_state)}


def _patient_brief(case_state: dict[str, Any]) -> str:
    chief = case_state.get("chief_complaint", {})
    pain = case_state.get("pain_profile", {})
    neuro = case_state.get("neuro_ortho", {})
    comorb = case_state.get("comorbidity", {})
    return f"我主要是{chief.get('standard_text') or chief.get('main_symptom') or '腰痛'}。疼痛部位{_join(pain.get('location'))}，放射情况{_join(pain.get('radiation'))}，下肢麻木{_join(neuro.get('numbness'))}。既往疾病/检查包括{_join(comorb.get('diseases'))}。这些信息供医生查看。"


def _clinician_case(case_state: dict[str, Any]) -> str:
    profile = case_state.get("patient_profile", {})
    chief = case_state.get("chief_complaint", {})
    tcm = case_state.get("tcm_inquiry", {})
    return f"患者{_join(profile.get('sex'))}，{_join(profile.get('age'))}岁。{chief.get('standard_text') or chief.get('main_symptom') or '腰痛待查'}。寒热：{_join(tcm.get('cold_heat'))}；睡眠：{_join(tcm.get('sleep'))}；胃纳：{_join(tcm.get('appetite'))}；舌象：{_join(tcm.get('tongue', {}).get('color'))}/{_join(tcm.get('tongue', {}).get('coating'))}，脉象待面诊复核。"
