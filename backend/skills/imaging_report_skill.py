"""Imaging / laboratory report assessment skill for lumbar-Bi CDSS.

This skill adds a dedicated "read the film / review tests" step to the agent flow. It
is deliberately report-first: official radiology/lab text, structured findings, or
operator-provided image links can be summarized and risk-graded, but the output never
replaces radiology interpretation, final diagnosis, or treatment decisions.
"""

from __future__ import annotations

import json
from typing import Any
import re

from backend.llm.dao_client import DaoClient, DaoRuntimeError
from backend.llm.json_repair import JsonRepairError, loads_with_repair
from backend.llm.output_guard import guard_clinician_draft

_RED_FLAG_TERMS = {
    "马尾": "possible_cauda_equina",
    "压缩骨折": "possible_fracture",
    "骨折": "possible_fracture",
    "肿瘤": "possible_tumor",
    "转移": "possible_tumor",
    "感染": "possible_infection",
    "脓肿": "possible_infection",
    "结核": "possible_infection",
    "严重椎管狭窄": "severe_stenosis",
}
_FINDING_TERMS = {
    "椎间盘突出": "disc_herniation",
    "椎间盘膨出": "disc_bulge",
    "椎管狭窄": "spinal_stenosis",
    "神经根受压": "nerve_root_compression",
    "黄韧带肥厚": "ligamentum_flavum_hypertrophy",
    "骨质增生": "spondylosis",
    "骨质疏松": "osteoporosis",
    "滑脱": "spondylolisthesis",
    "Modic": "modic_change",
    "终板炎": "endplate_change",
}
_LAB_TERMS = {
    "CRP": "inflammation_marker",
    "C反应蛋白": "inflammation_marker",
    "血沉": "inflammation_marker",
    "ESR": "inflammation_marker",
    "白细胞": "infection_marker",
    "尿酸": "uric_acid",
    "肌酐": "renal_function",
    "肝功能": "liver_function",
}


def _texts(items: list[dict[str, Any]] | list[str] | None) -> list[str]:
    out: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            parts = [str(item.get(k, "")) for k in ("modality", "date", "body_part", "text", "conclusion")]
            out.append(" ".join(p for p in parts if p).strip())
        else:
            out.append(str(item))
    return [t for t in out if t]


def _negated_near(text: str, start: int) -> bool:
    prefix = text[max(0, start - 8):start]
    return bool(re.search(r"(未见|未提示|无|没有|否认|排除|未发现|不考虑)\s*$", prefix))


def _scan(text: str, lexicon: dict[str, str]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for term, tag in lexicon.items():
        for match in re.finditer(re.escape(term), text, flags=re.IGNORECASE):
            if _negated_near(text, match.start()):
                continue
            hits.append({"term": term, "tag": tag})
            break
    return hits


def deterministic_imaging_report_assessment(
    case_state: dict[str, Any] | None = None,
    imaging_reports: list[dict[str, Any]] | list[str] | None = None,
    lab_reports: list[dict[str, Any]] | list[str] | None = None,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    report_texts = _texts(imaging_reports)
    lab_texts = _texts(lab_reports)
    combined = "\n".join(report_texts + lab_texts)
    findings = _scan(combined, _FINDING_TERMS)
    lab_findings = _scan(combined, _LAB_TERMS)
    red_flags = _scan(combined, _RED_FLAG_TERMS)
    evidence_packets = []
    for hit in findings + lab_findings + red_flags:
        evidence_packets.append({
            "source_type": "imaging_or_lab_report",
            "source_id": hit["tag"],
            "quote_or_summary": hit["term"],
            "supports": [hit["tag"]],
            "contradicts": [],
            "reliability": "moderate",
            "patient_visible": False,
        })
    if image_urls and not report_texts:
        evidence_packets.append({
            "source_type": "image_attachment",
            "source_id": "image_urls",
            "quote_or_summary": "提供了影像链接/附件；需视觉模型或正式报告复核。",
            "supports": ["needs_radiology_review"],
            "contradicts": [],
            "reliability": "unknown",
            "patient_visible": False,
        })
    lines = ["# 影像/检验检查评估（医师复核草案）"]
    if findings:
        lines.append("- 影像结构线索：" + "、".join(h["term"] for h in findings))
    else:
        lines.append("- 影像结构线索：报告文字不足或未识别到腰椎结构关键词。")
    if lab_findings:
        lines.append("- 检验线索：" + "、".join(h["term"] for h in lab_findings))
    if red_flags:
        lines.append("- ⚠️ 红旗影像/检验信号：" + "、".join(h["term"] for h in red_flags) + "；请优先线下/急诊或专科复核。")
    if image_urls and not report_texts:
        lines.append("- 已提供影像附件/链接，但若未启用视觉模型或缺少正式报告，不能仅凭附件作诊断。")
    lines.append("- 与沈医师腰痹经验的关系：影像/检验用于识别结构损害、神经压迫和现代医学风险；中医证型/方路仍需结合四诊、病程、舌脉和医师查体。")
    followups = ["请补充正式报告结论、检查日期、腰椎节段、是否神经受压，以及是否有发热/肿瘤史/外伤/大小便异常。"]
    return {
        "imaging_markdown": "\n".join(lines),
        "key_findings": findings + lab_findings,
        "red_flag_imaging_signals": red_flags,
        "evidence_packets": evidence_packets,
        "followup_questions": followups,
        "image_urls_seen": bool(image_urls),
        "clinician_only": True,
        "non_prescriptive": True,
        "llm_runtime": {"enabled": False, "status": "not_requested"},
    }


def imaging_report_skill(
    case_state: dict[str, Any] | None = None,
    imaging_reports: list[dict[str, Any]] | list[str] | None = None,
    lab_reports: list[dict[str, Any]] | list[str] | None = None,
    image_urls: list[str] | None = None,
    use_llm: bool = False,
    dao_client: DaoClient | None = None,
) -> dict[str, Any]:
    """Assess imaging/lab report findings as clinician-review evidence.

    ``use_llm=True`` can call any configured DaoClient backend. For the requested Poe
    Gemini path set ``TAO_BACKEND=poe`` and ``TAO_MODEL_ID=Gemini-3.1-Pro`` (or the Poe
    bot name exposed by the operator). If the backend fails or returns unsafe/non-JSON
    output, the deterministic assessment is returned.
    """

    deterministic = deterministic_imaging_report_assessment(case_state, imaging_reports, lab_reports, image_urls)
    meta = {"enabled": use_llm, "status": "not_requested", "backend": getattr(getattr(dao_client, "config", None), "backend", None)}
    if not use_llm:
        return {**deterministic, "llm_runtime": meta, "source": "deterministic"}
    client = dao_client or DaoClient()
    meta["backend"] = client.config.backend
    context = {
        "case_state": case_state or {},
        "imaging_reports": imaging_reports or [],
        "lab_reports": lab_reports or [],
        "image_urls": image_urls or [],
        "deterministic_assessment": deterministic,
    }
    try:
        raw = client.generate_imaging_assessment(context)
        parsed, repair_meta = loads_with_repair(raw)
        meta["json_repair"] = repair_meta
        markdown = str(parsed.get("imaging_markdown") or "").strip()
        guard = guard_clinician_draft(markdown)
        meta["guard"] = guard
        if markdown and guard["allowed"]:
            return {
                **deterministic,
                "imaging_markdown": markdown,
                "key_findings": parsed.get("key_findings") or deterministic["key_findings"],
                "red_flag_imaging_signals": parsed.get("red_flag_imaging_signals") or deterministic["red_flag_imaging_signals"],
                "followup_questions": parsed.get("followup_questions") or deterministic["followup_questions"],
                "llm_runtime": {**meta, "status": "accepted", "fallback_used": False},
                "source": "llm_guarded",
            }
        meta.update({"status": "fallback", "fallback_used": True, "error": "empty or guard-blocked imaging markdown"})
    except (DaoRuntimeError, JsonRepairError, ValueError, KeyError, TypeError) as exc:
        meta.update({"status": "fallback", "fallback_used": True, "error": str(exc)})
    return {**deterministic, "llm_runtime": meta, "source": "deterministic_fallback"}
