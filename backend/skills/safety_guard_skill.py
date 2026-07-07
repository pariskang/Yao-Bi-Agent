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
_EMERGENCY_CATEGORIES = {"cauda_equina_symptoms", "progressive_weakness", "fever_or_infection"}
# Trauma is urgent only against a fragility background; otherwise caution.
_FRAGILITY_TAGS = {"osteoporosis", "elderly", "very_elderly"}


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
    return False


def safety_guard_skill(case_json: dict[str, Any], matched_modules: list[dict[str, Any]] | None = None, normalized_tags: list[str] | None = None) -> dict[str, Any]:
    config = load_yaml(Path(RULES_DIR) / "07_safety_rules.yaml") or {}
    text = (case_json.get("evidence") or {}).get("raw_text", "")
    tags = set(normalized_tags or [])
    red_flag_messages: dict[str, str] = config.get("red_flags") or {}

    confirmed: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []

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
        if polarity == "affirmed":
            confirmed.append({**record, "message": f"原文红旗线索：{term}"})
        elif polarity == "negated":
            denied.append({**record, "message": f"患者已否认：{term}"})
        else:
            uncertain.append({**record, "message": f"红旗线索待澄清：{term}"})

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

    return {
        "safety_status": status,
        # Backward-compatible alias of confirmed_red_flags: only confirmed findings.
        "red_flags": confirmed,
        "confirmed_red_flags": confirmed,
        "denied_red_flags": denied,
        "uncertain_red_flags": uncertain,
        "need_further_inquiry": need_further_inquiry,
        "medication_risks": sorted(set(medication_risks)),
        "required_disclaimer": True,
        "disclaimer": config.get("required_disclaimer"),
    }
