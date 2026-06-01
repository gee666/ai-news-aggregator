"""LLM adjudication for uncertain story matches."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.ai.llm_client import LLMClient


@dataclass(slots=True)
class DedupDecision:
    same_story: bool
    confidence: float
    reason: str
    shared_facts: list[str] = field(default_factory=list)
    different_facts: list[str] = field(default_factory=list)
    recommended_relation: str = "separate"

    @property
    def auto_merge(self) -> bool:
        return self.same_story and self.confidence >= 0.85 and self.recommended_relation == "same_story"


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "same_story": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
        "shared_facts": {"type": "array", "items": {"type": "string"}},
        "different_facts": {"type": "array", "items": {"type": "string"}},
        "recommended_relation": {"type": "string", "enum": ["same_story", "related", "separate"]},
    },
    "required": ["same_story", "confidence", "reason", "shared_facts", "different_facts", "recommended_relation"],
    "additionalProperties": False,
}


class DedupJudge:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def judge(self, left: dict[str, Any], right: dict[str, Any]) -> DedupDecision:
        prompt = f"""Are these two summaries about the same real-world news event, or only related/same-topic?

Return JSON matching the schema.

Summary A:
{json.dumps(left, ensure_ascii=False, default=str)}

Summary B:
{json.dumps(right, ensure_ascii=False, default=str)}
"""
        response = await self.llm.complete(prompt, route="smart", json_schema=SCHEMA)
        data = json.loads(response.text or "{}")
        return DedupDecision(
            same_story=bool(data.get("same_story")),
            confidence=float(data.get("confidence") or 0),
            reason=str(data.get("reason") or ""),
            shared_facts=list(data.get("shared_facts") or []),
            different_facts=list(data.get("different_facts") or []),
            recommended_relation=str(data.get("recommended_relation") or "separate"),
        )


def is_configured() -> bool:
    from app.ai.llm_client import is_configured as llm_is_configured

    return llm_is_configured()
