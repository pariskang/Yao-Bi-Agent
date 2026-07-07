from __future__ import annotations

import re
from typing import Any

from backend.skills.clinical_entity_skill import affirmed_terms, scan_entities

FIELD_PATTERNS = {
    "sex": [(r"患者?(男|女)", 1), (r"性别[:：]?(男|女)", 1)],
    "age": [(r"(\d{1,3})\s*岁", 1)],
}

KEYWORDS = {
    "symptoms": [
        "腰痛", "腰腿痛", "下肢麻木", "腿麻", "畏寒", "怕冷", "口苦", "口干", "乏力", "腰膝酸软",
        "刺痛", "胀痛", "冷痛", "隐痛", "疼痛固定", "固定痛", "纳差", "胃纳差", "胃脘不适",
        "手脚凉", "四肢冷", "受凉加重", "遇冷加重", "热敷缓解", "扭伤", "劳损", "恶心", "失眠",
    ],
    "tongue": ["舌暗", "舌紫暗", "苔白腻", "苔腻", "舌淡", "舌红", "齿痕"],
    "pulse": ["脉细", "脉缓", "脉沉", "脉弦", "脉滑"],
    "western_diagnosis": ["骨质疏松", "腰椎间盘突出", "腰椎管狭窄", "腰椎滑脱", "压缩性骨折", "坐骨神经痛"],
}

# Red-flag surface terms → screening category. These are *candidates*: polarity
# resolution (affirmed / negated / uncertain) happens in clinical_entity_skill and the
# candidate→confirmed grading happens in safety_guard_skill — a raw keyword hit alone
# must never drive the safety status.
RED_FLAG_CATEGORY = {
    "外伤": "trauma_fracture_risk", "跌倒": "trauma_fracture_risk", "车祸": "trauma_fracture_risk",
    "高处坠落": "trauma_fracture_risk",
    "大小便失禁": "cauda_equina_symptoms", "大小便异常": "cauda_equina_symptoms",
    "大小便": "cauda_equina_symptoms", "会阴麻木": "cauda_equina_symptoms",
    "鞍区麻木": "cauda_equina_symptoms", "尿不出来": "cauda_equina_symptoms",
    "尿潴留": "cauda_equina_symptoms",
    "发热": "fever_or_infection", "寒战": "fever_or_infection", "感染": "fever_or_infection",
    "肿瘤": "cancer_history", "癌症": "cancer_history",
    "体重下降": "unexplained_weight_loss", "不明原因消瘦": "unexplained_weight_loss",
    "走路拖脚": "progressive_weakness", "进行性无力": "progressive_weakness",
}
RED_FLAG_TERMS = list(RED_FLAG_CATEGORY)
REQUIRED_FIELDS = ["疼痛性质", "是否放射痛", "夜寐", "胃纳", "二便", "舌象", "脉象"]

# Feeds the herb-drug / comorbidity interaction checker (rules/06_conflict_rules.yaml).
MEDICATION_TERMS = [
    "华法林", "阿司匹林", "利伐沙班", "氯吡格雷", "塞来昔布", "布洛芬", "双氯芬酸",
    "艾瑞昔布", "依托考昔", "泼尼松", "地塞米松", "二甲双胍", "乙哌立松",
]
COMORBIDITY_TERMS = [
    "高血压", "糖尿病", "冠心病", "心脏病", "心律失常", "心衰",
    "肝功能不全", "肾功能不全", "肝硬化", "尿毒症", "消化性溃疡", "胃溃疡",
    "妊娠", "怀孕", "低血钾", "水肿",
]


def _first_match(text: str, patterns: list[tuple[str, int]]) -> Any:
    for pattern, group in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(group)
            return int(value) if value.isdigit() else value
    return "unknown"


def _duration(text: str) -> str:
    match = re.search(r"(?:反复|病程|持续)?[^，。；;]{0,6}(\d+\s*(?:年|月|周|天))", text)
    return match.group(1).replace(" ", "") if match else "unknown"


def _main_complaint(text: str) -> str:
    match = re.search(r"(腰[^，。；;]*(?:年|月|周|天)?(?:，?加重\d+\s*(?:年|月|周|天))?)", text)
    return match.group(1).replace(" ", "") if match else "unknown"


def _duration_class(duration: str) -> str:
    if duration == "unknown":
        return "unknown"
    if "年" in duration:
        return "久病"
    if "月" in duration:
        return "亚急性或慢性"
    return "急性或短期"


def case_extract_skill(raw_text: str) -> dict[str, Any]:
    """Extract de-identified case fields without diagnosis or prescription."""
    extracted = {
        "age": _first_match(raw_text, FIELD_PATTERNS["age"]),
        "sex": _first_match(raw_text, FIELD_PATTERNS["sex"]),
        "main_complaint": _main_complaint(raw_text),
        "duration": _duration(raw_text),
    }
    extracted["duration_class"] = _duration_class(str(extracted["duration"]))
    evidence: dict[str, list[str]] = {}
    for field, terms in KEYWORDS.items():
        # Polarity-aware: "无恶心"、"未见齿痕" must not become positive findings.
        values = affirmed_terms(raw_text, terms)
        extracted[field] = values
        evidence[field] = values
    # Red flags as polarity-resolved entities: affirmed candidates keep the legacy
    # ``red_flags`` key; denials and questions are recorded separately so downstream
    # safety grading (safety_guard_skill) can distinguish them.
    rf_entities = scan_entities(raw_text, RED_FLAG_CATEGORY, category_map=RED_FLAG_CATEGORY)
    extracted["red_flag_entities"] = rf_entities
    extracted["red_flags"] = [e["entity"] for e in rf_entities if e["polarity"] == "affirmed"]
    extracted["denied_red_flags"] = [e["entity"] for e in rf_entities if e["polarity"] == "negated"]
    extracted["uncertain_red_flags"] = [e["entity"] for e in rf_entities if e["polarity"] == "uncertain"]
    extracted["medications"] = affirmed_terms(raw_text, MEDICATION_TERMS)
    extracted["comorbidity_conditions"] = affirmed_terms(raw_text, COMORBIDITY_TERMS)
    missing = []
    if not any(term in raw_text for term in ["酸痛", "刺痛", "胀痛", "冷痛", "隐痛"]):
        missing.append("疼痛性质")
    if not any(term in raw_text for term in ["放射", "臀", "小腿", "足", "坐骨"]):
        missing.append("是否放射痛")
    for label, terms in {
        "夜寐": ["夜寐", "睡眠", "失眠"],
        "胃纳": ["胃纳", "胃口", "纳差"],
        "二便": ["大便", "小便", "二便"],
        "舌象": ["舌"],
        "脉象": ["脉"],
    }.items():
        if not any(term in raw_text for term in terms):
            missing.append(label)
    extracted["missing_fields"] = missing
    extracted["evidence"] = {"raw_text": raw_text, **evidence}
    return extracted
