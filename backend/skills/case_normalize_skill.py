from __future__ import annotations

from typing import Any

TAG_MAP = {
    "腰痛": "lumbar_pain",
    "腰腿痛": "lumbar_leg_pain",
    "下肢麻木": "lower_limb_numbness",
    "腿麻": "lower_limb_numbness",
    "畏寒": "cold_aversion",
    "怕冷": "cold_aversion",
    "舌暗": "dark_tongue",
    "舌紫暗": "purple_tongue",
    "苔白腻": "white_greasy_coating",
    "苔腻": "greasy_coating",
    "脉缓": "slow_pulse",
    "脉细": "thin_pulse",
    "口苦": "bitter_taste",
    "口干": "dry_mouth",
    "夜寐差": "insomnia",
    "睡眠差": "insomnia",
    "胃纳差": "poor_appetite",
    "胃脘不适": "epigastric_discomfort",
    "乏力": "fatigue",
    "骨质疏松": "osteoporosis",
}


def case_normalize_skill(case_json: dict[str, Any]) -> dict[str, Any]:
    tags: set[str] = set()
    evidence: dict[str, list[str]] = {}
    age = case_json.get("age")
    if isinstance(age, int):
        if age >= 60:
            tags.add("elderly")
            evidence.setdefault("elderly", []).append(f"年龄{age}岁")
        if age >= 73:
            tags.add("very_elderly")
            evidence.setdefault("very_elderly", []).append(f"年龄{age}岁")
        if age <= 40:
            tags.add("young_patient")
            evidence.setdefault("young_patient", []).append(f"年龄{age}岁")
    if case_json.get("duration_class") == "久病":
        tags.update(["chronic_yabi", "long_duration"])
        evidence.setdefault("chronic_yabi", []).append(str(case_json.get("duration")))
    for field in ["symptoms", "tongue", "pulse", "western_diagnosis"]:
        for value in case_json.get(field) or []:
            tag = TAG_MAP.get(value)
            if tag:
                tags.add(tag)
                evidence.setdefault(tag, []).append(value)
    text = (case_json.get("evidence") or {}).get("raw_text", "")
    if any(term in text for term in ["放射", "坐骨", "小腿", "足部"]):
        tags.add("radiating_leg_pain")
        evidence.setdefault("radiating_leg_pain", []).append("原文提示放射或远端下肢受累")
    return {"normalized_tags": sorted(tags), "tag_evidence": evidence}
