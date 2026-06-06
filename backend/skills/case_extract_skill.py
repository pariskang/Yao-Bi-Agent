from __future__ import annotations

import re
from typing import Any

FIELD_PATTERNS = {
    "sex": [(r"患者?(男|女)", 1), (r"性别[:：]?(男|女)", 1)],
    "age": [(r"(\d{1,3})\s*岁", 1)],
}

KEYWORDS = {
    "symptoms": ["腰痛", "腰腿痛", "下肢麻木", "腿麻", "畏寒", "怕冷", "口苦", "口干", "乏力", "腰膝酸软"],
    "tongue": ["舌暗", "舌紫暗", "苔白腻", "苔腻", "舌淡", "舌红"],
    "pulse": ["脉细", "脉缓", "脉沉", "脉弦", "脉滑"],
    "western_diagnosis": ["骨质疏松", "腰椎间盘突出", "腰椎管狭窄", "腰椎滑脱", "压缩性骨折", "坐骨神经痛"],
}

RED_FLAG_TERMS = ["外伤", "跌倒", "车祸", "大小便", "会阴麻木", "尿不出来", "发热", "寒战", "肿瘤", "体重下降", "走路拖脚"]
REQUIRED_FIELDS = ["疼痛性质", "是否放射痛", "夜寐", "胃纳", "二便", "舌象", "脉象"]


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
        values = [term for term in terms if term in raw_text]
        extracted[field] = values
        evidence[field] = values
    red_flags = [term for term in RED_FLAG_TERMS if term in raw_text]
    extracted["red_flags"] = red_flags
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
