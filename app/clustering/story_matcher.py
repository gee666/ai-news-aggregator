"""Hybrid deterministic + LLM story matching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai.dedup_judge import DedupJudge
from app.clustering.candidate_search import Candidate


@dataclass(slots=True)
class MatchDecision:
    same_story: bool
    confidence: float
    reason: str
    relation_type: str | None = None

    @property
    def should_merge(self) -> bool:
        return self.same_story and self.confidence >= 0.85


class StoryMatcher:
    def __init__(self, judge: DedupJudge | None = None) -> None:
        self.judge = judge or DedupJudge()

    async def match(self, incoming: dict[str, Any], candidate: Candidate) -> MatchDecision:
        deterministic = deterministic_match(incoming, candidate)
        if deterministic:
            return deterministic
        if candidate.similarity < 0.78:
            return MatchDecision(False, candidate.similarity, "embedding_below_uncertain_threshold", "related")
        decision = await self.judge.judge(incoming, candidate_to_dict(candidate))
        if decision.auto_merge and not has_conflicting_metadata(incoming, candidate.metadata or {}):
            return MatchDecision(True, decision.confidence, f"llm: {decision.reason}")
        relation = "related" if decision.recommended_relation == "related" else "separate"
        return MatchDecision(False, decision.confidence, f"llm: {decision.reason}", relation)


def deterministic_match(incoming: dict[str, Any], candidate: Candidate) -> MatchDecision | None:
    checks = [
        ("canonical_url", candidate.canonical_url, "same_url"),
        ("root_source_url", candidate.root_source_url, "same_root_url"),
        ("content_hash", candidate.content_hash, "same_content_hash"),
    ]
    for key, candidate_value, reason in checks:
        incoming_value = incoming.get(key)
        if incoming_value and candidate_value and incoming_value == candidate_value:
            return MatchDecision(True, 1.0, reason)
    return None


def has_conflicting_metadata(incoming: dict[str, Any], candidate_metadata: dict[str, Any]) -> bool:
    for key in ("event_type", "event_date"):
        left = incoming.get(key)
        right = candidate_metadata.get(key)
        if left and right and left != right:
            return True
    return False


def candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "summary_id": str(candidate.summary_id),
        "title": candidate.title,
        "summary_text": candidate.summary_text,
        "canonical_url": candidate.canonical_url,
        "root_source_url": candidate.root_source_url,
        "content_hash": candidate.content_hash,
        "similarity": candidate.similarity,
        "metadata": candidate.metadata or {},
    }


def is_configured() -> bool:
    return True
