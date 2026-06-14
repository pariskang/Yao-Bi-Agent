"""Tao-primary grounded consultation: the language model is the main reasoner.

The deterministic rule engine and de-identified mining provide *grounding evidence*
(candidate syndromes, formula routes, herb modules, safety flags, Shen experience signals,
mined statistics); the model then combines that with its own TCM knowledge and writes a
deep, professional clinician-facing analysis. This inverts the overlay-only design for the
answer text while keeping the safety floor:

* the answer passes ``guard_consultation`` (clinician draft may name formulas / 方义 /
  experience dose ranges, but never patient self-administration; patient role stays strict);
* on any failure / guard rejection / disabled runtime it falls back to the deterministic
  rule answer, so the system never regresses below the rule baseline.
"""

from __future__ import annotations

from typing import Any

from backend.llm.dao_client import DaoClient, DaoRuntimeError
from backend.llm.output_guard import guard_consultation

_DISCLAIMER = "\n\n> 本分析为供执业医师审核的研究 / 教学草案，最终诊断与处方须医师面诊后确定，患者不可据此自行用药。"


def tao_consultation_skill(
    question: str,
    scope: str,
    evidence: dict[str, Any],
    *,
    fallback_text: str,
    dao_client: DaoClient | None = None,
    use_llm: bool = False,
    user_role: str = "clinician",
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "enabled": use_llm,
        "status": "not_requested" if not use_llm else "pending",
        "fallback_used": True,
        "backend": getattr(getattr(dao_client, "config", None), "backend", None),
        "guard": None,
    }
    if not use_llm:
        return {"answer": fallback_text, "source": "deterministic_rules", "used_llm": False, "tao_runtime": meta}

    client = dao_client or DaoClient()
    meta["backend"] = client.config.backend
    try:
        raw = client.generate_consultation({"question": question, "scope": scope, "evidence": evidence, "user_role": user_role})
        text = (raw or "").strip()
        guard = guard_consultation(text, user_role)
        meta["guard"] = guard
        if not text or not guard["allowed"]:
            meta["status"] = "guard_rejected" if text else "empty"
            return {"answer": fallback_text, "source": "deterministic_rules_fallback", "used_llm": False, "tao_runtime": meta}
        if "执业医师" not in text[-160:]:
            text += _DISCLAIMER
        meta.update({"status": "accepted", "fallback_used": False})
        return {"answer": text, "source": "tao_primary_grounded", "used_llm": True, "tao_runtime": meta}
    except DaoRuntimeError as exc:
        meta.update({"status": "fallback", "error": str(exc)})
        return {"answer": fallback_text, "source": "deterministic_rules_fallback", "used_llm": False, "tao_runtime": meta}
