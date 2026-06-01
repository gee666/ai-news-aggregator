"""Cheap-model structured extraction for clustering metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.ai.llm_client import LLMClient


@dataclass(slots=True)
class ExtractedStoryMetadata:
    entities: list[str] = field(default_factory=list)
    event_type: str | None = None
    event_date: str | None = None
    products: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entities": {"type": "array", "items": {"type": "string"}},
        "event_type": {"type": ["string", "null"]},
        "event_date": {"type": ["string", "null"]},
        "products": {"type": "array", "items": {"type": "string"}},
        "companies": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["entities", "event_type", "event_date", "products", "companies"],
    "additionalProperties": False,
}


class MetadataExtractor:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def extract(self, title: str, summary: str) -> ExtractedStoryMetadata:
        prompt = f"Extract clustering metadata from this news summary.\n\nTitle: {title}\n\nSummary:\n{summary}"
        response = await self.llm.complete(prompt, route="cheap", json_schema=SCHEMA)
        data = json.loads(response.text or "{}")
        return ExtractedStoryMetadata(
            entities=list(data.get("entities") or []),
            event_type=data.get("event_type"),
            event_date=data.get("event_date"),
            products=list(data.get("products") or []),
            companies=list(data.get("companies") or []),
            raw=data,
        )


def is_configured() -> bool:
    from app.ai.llm_client import is_configured as llm_is_configured

    return llm_is_configured()
