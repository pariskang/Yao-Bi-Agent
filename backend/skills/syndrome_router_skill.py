from __future__ import annotations

from typing import Any

from backend.contracts import SYNDROME_RESULT, validate
from backend.engine.rule_engine import RuleEngine


def syndrome_router_skill(normalized_tags: list[str]) -> dict[str, Any]:
    engine = RuleEngine(["02_syndrome_rules.yaml"])
    candidates, rule_hits = engine.score_syndromes(normalized_tags)
    return validate({"syndrome_candidates": candidates, "rule_hits": rule_hits}, SYNDROME_RESULT, "syndrome_router_skill")
