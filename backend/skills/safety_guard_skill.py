"""Red-flag safety grading: candidate → polarity check → confirmed red flag.

A raw keyword hit is only a *candidate*. The extraction layer resolves its polarity
(clinical_entity_skill), and this skill grades the outcome:

* ``confirmed_red_flags`` — affirmed findings; the only ones that may drive the
  safety status;
* ``denied_red_flags`` — pertinent negatives ("否认外伤"、"无发热寒战"), recorded for
  the audit trail but never alarming;
* ``uncertain_red_flags`` — questions/hedges; they yield ``need_further_inquiry``
  follow-ups and cap the status at "caution", never "urgent".

Urgency is category-tiered instead of the old "any raw keyword ⇒ urgent" rule:
cauda equina and progressive weakness are always urgent when confirmed; fever with
back pain is an infection red flag (urgent); trauma escalates to urgent only with a
fragility context (osteoporosis / elderly / severe pain); cancer history escalates
with night pain or unexplained weight loss, otherwise it is a caution-level flag.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.engine.rule_engine import RULES_DIR, load_yaml
from backend.skills.case_extract_skill import RED_FLAG_CATEGORY
from backend.skills.clinical_entity_skill import is_affirmed

TAG_REDFLAG_MAP = {
    "trauma_fracture_risk": "trauma_fracture_risk",
    "cauda_equina_symptoms": "cauda_equina_symptoms",
    "progressive_weakness": "progressive_weakness",
    "fever_or_infection": "fever_or_infection",
    "cancer_history": "cancer_history",
    "unexplained_weight_loss": "unexplained_weight_loss",
    "anticoagulant_use": "anticoagulant_use",
}

# Confirmed findings in these categories are urgent regardless of context.
# v0.10 orthopedic safety ontology: beyond the original spine triad, high-energy
# trauma, open fracture/dislocation, neurovascular deficit, compartment syndrome,
# vascular and cardiopulmonary emergencies and cervical myelopathy all hard-halt.
_EMERGENCY_CATEGORIES = {
    "cauda_equina_symptoms", "progressive_weakness", "fever_or_infection",
    "major_trauma", "open_fracture_dislocation", "neurovascular_deficit",
    "compartment_syndrome", "vascular_emergency", "cardiopulmonary_emergency",
    "cervical_myelopathy",
}
# Trauma is urgent only against a fragility background; otherwise caution.
_FRAGILITY_TAGS = {"osteoporosis", "elderly", "very_elderly"}

# Categories where a *historical* finding is itself the red flag (a past tumor is the
# point of asking); every other category requires a current/unresolved finding —
# "一周前发热，现已痊愈" must not trigger a current infection hard stop.
_HISTORY_RELEVANT_CATEGORIES = {"cancer_history"}

# Categories that hard-halt TCM reasoning entirely (emergency referral is the only
# valid output). Contextual-urgent flags (e.g. fragility trauma) still mark the case
# urgent but leave the retrospective clinician-review analysis available.
EMERGENCY_HALT_CATEGORIES = frozenset(_EMERGENCY_CATEGORIES)


def emergency_halt_required(safety: dict[str, Any]) -> bool:
    """True when confirmed red flags demand an emergency halt of the clinical chain.

    This is the single gate predicate every entry path shares (pipeline, chat,
    autonomous agent, orchestrator): an urgent status caused by an always-emergency
    category (cauda equina / progressive weakness / infection) means no syndrome,
    formula or herb output may be produced — only the referral notice.
    """

    if safety.get("safety_status") != "urgent":
        return False
    categories = {flag.get("category") for flag in safety.get("confirmed_red_flags") or []}
    return bool(categories & EMERGENCY_HALT_CATEGORIES)


def _term_category(term: str) -> str | None:
    for key, category in RED_FLAG_CATEGORY.items():
        if key in term:
            return category
    return None


def _confirmed_urgent(confirmed: list[dict[str, Any]], tags: set[str], text: str) -> bool:
    categories = {flag.get("category") for flag in confirmed}
    if categories & _EMERGENCY_CATEGORIES:
        return True
    if "trauma_fracture_risk" in categories and (
        tags & _FRAGILITY_TAGS or is_affirmed(text, "剧痛") or "压缩性骨折" in text
    ):
        return True
    if "cancer_history" in categories and (
        "unexplained_weight_loss" in categories or is_affirmed(text, "夜间痛")
    ):
        return True
    if "immunosuppressed_risk" in categories:
        return True
    return False


def _combination_flags(text: str, tags: set[str], confirmed_categories: set[str]) -> list[dict[str, Any]]:
    """Multi-sign escalations no single keyword captures (orthopedic ontology v0.10).

    * suspected PE: calf swelling/pain plus dyspnea/palpitation after immobilisation —
      each sign alone is benign-ish (气短 is also a TCM qi-deficiency cue), together
      they are a cardiopulmonary emergency;
    * immunosuppressed red-flag context: biologics/long-term steroids plus night pain
      or infection signs → infection/malignancy high-risk (contextual urgent referral,
      not an emergency halt — the workup is urgent, the scene is not a resuscitation).
    """

    combos: list[dict[str, Any]] = []
    if is_affirmed(text, "小腿肿") and (
        is_affirmed(text, "气短") or is_affirmed(text, "呼吸困难") or is_affirmed(text, "心慌")
    ):
        combos.append({
            "id": "cardiopulmonary_emergency", "category": "cardiopulmonary_emergency",
            "term": "小腿肿痛+气短/心慌", "source": "combination",
            "message": "制动/骨折背景下小腿肿痛伴气短、心慌需警惕肺栓塞，立即急诊评估。",
        })
    immunosuppressed = "immunosuppressant_use" in tags or any(
        is_affirmed(text, term) for term in ("生物制剂", "免疫抑制剂", "长期激素", "长期使用激素")
    )
    if immunosuppressed and ("night_pain" in tags or "fever_or_infection" in confirmed_categories):
        combos.append({
            "id": "immunosuppressed_risk", "category": "immunosuppressed_risk",
            "term": "免疫抑制+夜间痛/感染线索", "source": "combination",
            "message": "免疫抑制患者腰痛伴夜间痛或感染线索，属感染/肿瘤高风险，需尽快专科评估。",
        })
    return combos


def safety_guard_skill(case_json: dict[str, Any], matched_modules: list[dict[str, Any]] | None = None, normalized_tags: list[str] | None = None) -> dict[str, Any]:
    config = load_yaml(Path(RULES_DIR) / "07_safety_rules.yaml") or {}
    text = (case_json.get("evidence") or {}).get("raw_text", "")
    tags = set(normalized_tags or [])
    red_flag_messages: dict[str, str] = config.get("red_flags") or {}

    confirmed: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []

    # 1) Controlled-vocabulary tags (already polarity-resolved upstream).
    for key, message in red_flag_messages.items():
        if key in tags:
            confirmed.append({"id": key, "category": key, "message": message, "source": "normalized_tag"})

    # 2) Narrative candidates. Preferred path: polarity-resolved entities from the
    # extractor. Legacy path (questionnaire positives / manual case_state): bare
    # strings are treated as already-confirmed items and classified by keyword.
    entities = case_json.get("red_flag_entities")
    if entities is None:
        entities = [
            {"entity": str(term), "polarity": "affirmed", "category": _term_category(str(term))}
            for term in case_json.get("red_flags") or []
        ]
    for entity in entities:
        term = str(entity.get("entity") or "")
        category = entity.get("category") or _term_category(term)
        record: dict[str, Any] = {
            "id": category or "raw_red_flag",
            "category": category,
            "term": term,
            "source": "narrative",
        }
        polarity = entity.get("polarity")
        temporality = entity.get("temporality") or "current"
        if polarity == "affirmed" and temporality in {"historical", "resolved"} \
                and category not in _HISTORY_RELEVANT_CATEGORIES:
            # The NLP layer resolved the temporal status — the safety layer must consume
            # it: a resolved/past finding is recorded for the physician, never alarmed.
            historical.append({**record, "temporality": temporality,
                               "message": f"既往/已缓解线索：{term}（不作为当前红旗，供医师参考）"})
        elif polarity == "affirmed":
            confirmed.append({**record, "message": f"原文红旗线索：{term}"})
        elif polarity == "negated":
            denied.append({**record, "message": f"患者已否认：{term}"})
        else:
            uncertain.append({**record, "message": f"红旗线索待澄清：{term}"})

    # 3) Combination escalations (PE pattern, immunosuppressed context).
    confirmed_categories = {flag.get("category") for flag in confirmed}
    confirmed.extend(_combination_flags(text, tags, confirmed_categories))

    if "自服" in text or "自己买药" in text or "开方" in text:
        confirmed.append({
            "id": "self_medication_request", "category": "self_medication_request",
            "message": red_flag_messages.get("self_medication_request", "自行购药/自服请求必须拒绝并转为医生复核建议。"),
            "source": "narrative",
        })

    high_risk = set(config.get("toxic_or_high_risk_herbs") or [])
    medication_risks = []
    for module in matched_modules or []:
        # Herb modules carry "herbs"; formula routes carry "core_module" — both are
        # draft herb pools that must be screened for toxic/high-risk entries.
        pool = set(module.get("herbs") or []) | set(module.get("core_module") or [])
        risky = sorted(high_risk & pool)
        if risky:
            medication_risks.append(f"{', '.join(risky)} 属于需严格医生审核的高风险/特殊药物，不可自行使用。")

    if _confirmed_urgent(confirmed, tags, text):
        status = "urgent"
    elif confirmed or uncertain or medication_risks:
        status = "caution"
    else:
        status = "safe"

    need_further_inquiry = [f"请澄清是否存在：{flag['term']}" for flag in uncertain if flag.get("term")]

    # Clinical action stratification: one blended "caution" cannot distinguish "car
    # crash, cannot stand" from "this herb needs physician review". The action level
    # states what should happen; the drivers state *why* — urgency, medication review
    # and missing evidence are separate axes, not one bucket.
    categories = {flag.get("category") for flag in confirmed}
    if status == "urgent" and categories & _EMERGENCY_CATEGORIES:
        action_level, action_meaning = "A0", "立即急救/急诊评估；硬停止全部辨证与方药推理"
    elif status == "urgent":
        action_level, action_meaning = "A1", "当日紧急专科评估；停止患者端方药建议（医师复盘分析保留）"
    elif status == "caution":
        action_level, action_meaning = "A2", "尽快线下面诊与检查；可继续采集信息，不生成可执行治疗内容"
    else:
        action_level, action_meaning = "A3", "常规门诊决策支持；可进入辨证与辅助分析"

    return {
        "safety_status": status,
        "action_level": action_level,
        "action_meaning": action_meaning,
        "drivers": {
            "clinical_urgency": status if status != "safe" else None,
            "medication_review_required": bool(medication_risks),
            "evidence_insufficient": bool(uncertain or need_further_inquiry),
        },
        # Backward-compatible alias of confirmed_red_flags: only confirmed findings.
        "red_flags": confirmed,
        "confirmed_red_flags": confirmed,
        "denied_red_flags": denied,
        "uncertain_red_flags": uncertain,
        # Past/resolved findings: physician-visible record, never an alarm driver.
        "historical_red_flags": historical,
        "need_further_inquiry": need_further_inquiry,
        "medication_risks": sorted(set(medication_risks)),
        "required_disclaimer": True,
        "disclaimer": config.get("required_disclaimer"),
    }
