from __future__ import annotations

from typing import Any

from backend.skills.caseguide_utils import load_caseguide_questions


def red_flag_screen_skill(answers: dict[str, Any] | None = None) -> dict[str, Any]:
    questions = load_caseguide_questions().get("red_flag_questions", [])
    if answers is None:
        return {"red_flag_questions": questions, "red_flag_status": "unknown", "next_action": "ask_red_flag_questions"}
    positive_flags = []
    caution_flags = []
    for question in questions:
        answer = answers.get(question["id"])
        if answer in (question.get("urgent_if") or []):
            positive_flags.append(question["label"])
        if answer in (question.get("caution_if") or []):
            caution_flags.append(question["label"])
        if answer == "不确定" and not question.get("caution_if"):
            caution_flags.append(question["label"])
    status = "urgent" if positive_flags else "caution" if caution_flags else "safe"
    if status == "urgent":
        message = "这些表现可能提示严重神经受压、骨折、感染或其他风险，请尽快线下就医或急诊评估。"
        next_action = "stop_and_refer"
    elif status == "caution":
        message = "存在需要医生重点复核的风险线索，可继续整理医案，但不应延误线下评估。"
        next_action = "continue_with_caution"
    else:
        message = "目前未发现必须立即就医的危险信号，可以继续整理医案。"
        next_action = "continue_case_collection"
    return {"red_flag_status": status, "positive_flags": positive_flags + caution_flags, "next_action": next_action, "message": message}
