from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from backend.engine.scoring import confidence_from_score

ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = ROOT / "rules"


def load_yaml(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_rule_file(name: str) -> Any:
    return load_yaml(RULES_DIR / name)


def trigger_matches(trigger: dict[str, Any] | None, tags: Iterable[str]) -> bool:
    if not trigger:
        return True
    tag_set = set(tags)
    all_terms = set(trigger.get("all") or [])
    any_terms = set(trigger.get("any") or [])
    at_least = trigger.get("at_least")

    if all_terms and not all_terms.issubset(tag_set):
        return False
    if any_terms:
        hits = any_terms & tag_set
        if at_least is not None:
            if len(hits) < int(at_least):
                return False
        elif not hits:
            return False
    return True


def matched_terms(trigger: dict[str, Any] | None, tags: Iterable[str]) -> list[str]:
    if not trigger:
        return []
    tag_set = set(tags)
    terms = set(trigger.get("all") or []) | set(trigger.get("any") or [])
    return sorted(terms & tag_set)


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    rule_name: str
    matched: bool
    evidence_tags: list[str]
    effect: dict[str, Any]
    rationale: str
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "matched": self.matched,
            "evidence_tags": self.evidence_tags,
            "effect": self.effect,
            "rationale": self.rationale,
            "priority": self.priority,
        }


class RuleEngine:
    def __init__(self, rule_files: list[str] | None = None) -> None:
        self.rule_files = rule_files or ["02_syndrome_rules.yaml", "03_formula_rules.yaml"]
        self.rules = []
        for file_name in self.rule_files:
            loaded = load_rule_file(file_name) or []
            self.rules.extend(loaded)

    def match(self, tags: Iterable[str], category: str | None = None) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for rule in self.rules:
            if category and rule.get("category") != category:
                continue
            trigger = rule.get("trigger", {})
            if trigger_matches(trigger, tags):
                hits.append(
                    RuleHit(
                        rule_id=rule["id"],
                        rule_name=rule["name"],
                        matched=True,
                        evidence_tags=matched_terms(trigger, tags),
                        effect=rule.get("effect", {}),
                        rationale=rule.get("rationale", ""),
                        priority=int(rule.get("priority", 0)),
                    )
                )
        return sorted(hits, key=lambda h: (h.priority, h.rule_id), reverse=True)

    def score_syndromes(self, tags: Iterable[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        scores: dict[str, int] = defaultdict(int)
        evidence: dict[str, list[str]] = defaultdict(list)
        hits = self.match(tags, category="syndrome")
        for hit in hits:
            syndrome = hit.effect.get("syndrome")
            if not syndrome:
                continue
            # Base rule score plus a corroboration bonus: every matched evidence tag
            # beyond the second strengthens the candidate, so richly supported syndromes
            # can actually reach "high" confidence (a single rule caps the base at 5).
            bonus = max(0, len(set(hit.evidence_tags)) - 2)
            scores[syndrome] += int(hit.effect.get("score", 0)) + bonus
            evidence[syndrome].extend(hit.evidence_tags)
        candidates = []
        for name, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
            confidence = confidence_from_score(score)
            candidates.append({
                "name": name,
                "score": score,
                "confidence": confidence,
                "evidence_tags": sorted(set(evidence[name])),
            })
        return candidates, [h.to_dict() for h in hits]
