from __future__ import annotations

import re
from typing import Any

PII_PATTERNS = [
    (re.compile(r"1[3-9]\d{9}"), "[手机号已脱敏]"),
    (re.compile(r"\d{17}[0-9Xx]"), "[身份证号已脱敏]"),
    (re.compile(r"[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}"), "[邮箱已脱敏]"),
]


def desensitize_text(raw_input: str) -> str:
    text = raw_input
    for pattern, repl in PII_PATTERNS:
        text = pattern.sub(repl, text)
    text = re.sub(r"(?:姓名|名字)[:：]?[^，。；;\s]{1,8}", "姓名：[已脱敏]", text)
    text = re.sub(r"(?:住址|地址)[:：]?[^，。；;]{3,40}", "地址：[已脱敏]", text)
    return text


def consent_privacy_skill(user_role: str = "patient", raw_input: str = "") -> dict[str, Any]:
    safe_text = desensitize_text(raw_input)
    return {
        "consent_required": True,
        "privacy_notice": True,
        "allowed_next_step": "red_flag_screen",
        "sanitized_input": safe_text,
        "patient_facing_message": "我可以帮你把腰痛情况整理成一份标准医案，供医生查看。这个过程不会替代医生诊断，也不会直接给出处方。",
        "required_homepage_notice": "本工具仅用于医案整理和医生沟通，不构成诊断、处方或治疗建议。",
        "forbidden_outputs": ["最终诊断", "临床处方", "患者自服剂量", "替代医生的治疗建议"],
    }
