from __future__ import annotations

from typing import Any


def chief_complaint_skill(main_symptom: str | None = None, duration: str | None = None, recurrent_status: str | None = None, acute_worsening: str | None = None, associated_symptom: str | None = None) -> dict[str, Any]:
    pieces = []
    symptom = main_symptom or "腰痛"
    if recurrent_status and "反复" in recurrent_status and duration:
        text = f"反复{symptom}{duration}"
    elif duration:
        text = f"{symptom}{duration}"
    else:
        text = symptom
    if acute_worsening:
        text += f"，加重{acute_worsening}"
    if associated_symptom:
        text += f"，伴{associated_symptom}"
    pieces.append(text)
    return {
        "chief_complaint": "".join(pieces),
        "evidence": {
            "main_symptom": main_symptom,
            "duration": duration,
            "acute_worsening": acute_worsening,
            "associated_symptom": associated_symptom,
            "recurrent_status": recurrent_status,
        },
    }
