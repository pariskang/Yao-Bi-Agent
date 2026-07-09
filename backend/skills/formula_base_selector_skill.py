from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.engine.rule_engine import RuleEngine
from backend.engine.scoring import confidence_from_score

# Syndrome-level tags derived from the syndrome router's candidates — the registered
# bridge between the syndrome layer and formula/module triggers. The rule lint
# (tests/test_rule_lint.py) treats DERIVED_TAGS as the only tags a rule may reference
# without a text-alias entry in rules/01_tags.yaml.
SYNDROME_DERIVED_TAGS = {
    "肝肾不足证": "ganshen_buzu",
    "肾阳不足证": "kidney_yang_deficiency",
    "寒湿痹阻证": "cold_damp_obstruction",
    "气滞血瘀证": "stasis_pattern",
}
DERIVED_TAGS = frozenset(SYNDROME_DERIVED_TAGS.values())


def formula_base_selector_skill(normalized_tags: list[str], syndrome_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    tags = set(normalized_tags)
    for candidate in syndrome_candidates:
        derived = SYNDROME_DERIVED_TAGS.get(candidate.get("name") or "")
        if derived:
            tags.add(derived)
    engine = RuleEngine(["03_formula_rules.yaml"])
    hits = engine.match(tags, category="formula")
    scores: dict[str, int] = defaultdict(int)
    route_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for hit in hits:
        route = hit.effect.get("formula_route")
        if route:
            # Same corroboration bonus as syndrome scoring: evidence beyond two tags
            # strengthens the route, making "high" confidence reachable. Contradicting
            # case tags (the rule's `contra` list) subtract, mirroring syndrome scoring.
            bonus = max(0, len(set(hit.evidence_tags)) - 2)
            penalty = RuleEngine.CONTRA_PENALTY * len(hit.contra_tags)
            scores[route] += int(hit.effect.get("route_score", 0)) + bonus - penalty
            route_hits[route].append(hit.to_dict())
    routes = []
    for route, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        if score <= 0:
            continue
        first = route_hits[route][0]
        routes.append({
            "name": route,
            "score": score,
            "confidence": confidence_from_score(score),
            "core_module": first["effect"].get("core_module", []),
            "evidence_tags": first["evidence_tags"],
            "rationale": first["rationale"],
            "non_prescriptive": True,
        })
    return {"formula_routes": routes, "primary_route": routes[0] if routes else None, "formula_rule_hits": [h.to_dict() for h in hits]}
