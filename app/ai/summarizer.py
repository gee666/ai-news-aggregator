"""AI summarization helpers that preserve auditable source links."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.ai.llm_client import LLMClient

PROMPT_VERSION = "summary-v1"
TEMPLATE_VERSION = "trusted-links-v1"


@dataclass(slots=True)
class SourceLink:
    url: str
    normalized_url: str | None = None
    canonical_url: str | None = None
    domain: str | None = None
    link_type: str | None = None
    trust_level: str | None = None
    title: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(slots=True)
class SummaryResult:
    summary_title: str
    summary_text: str
    source_links: list[SourceLink] = field(default_factory=list)
    model_name: str | None = None
    prompt_version: str = PROMPT_VERSION
    summary_template_version: str = TEMPLATE_VERSION

    def storage_fields(self) -> dict[str, Any]:
        links = [link.to_json() for link in self.source_links]
        return {
            "summary_title": self.summary_title,
            "summary_text": self.summary_text,
            "summary_template_version": self.summary_template_version,
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
            "source_links_json": links,
            "summary_links": links,
        }


class Summarizer:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def summarize_bundle(
        self,
        *,
        root_text: str,
        secondary_texts: list[str] | None = None,
        raw_context: str | None = None,
        links: list[SourceLink] | None = None,
    ) -> SummaryResult:
        source_links = links or []
        prompt = build_summary_prompt(root_text, secondary_texts or [], raw_context, source_links)
        response = await self.llm.complete(
            prompt,
            route="smart",
            instructions="You summarize trusted news source bundles. Preserve the supplied links exactly.",
        )
        title, text = split_title(response.text)
        return SummaryResult(title, text, source_links, response.model)


def build_summary_prompt(
    root_text: str, secondary_texts: list[str], raw_context: str | None, links: list[SourceLink]
) -> str:
    link_lines = "\n".join(f"{i + 1}. {json.dumps(link.to_json(), ensure_ascii=False)}" for i, link in enumerate(links))
    secondary = "\n\n--- Secondary source ---\n".join(secondary_texts)
    return f"""Create a concise news summary from trusted source material only.

Required output format:
Title: <short factual title>

What happened:
<paragraph>

Why it matters:
<paragraph>

Key facts:
- <fact>

Source quality:
- Root source: <describe>
- Secondary sources: <describe or none>

Links:
1. <preserve exact URL and label from supplied links>

Root/official source text:
{root_text}

Trusted secondary sources:
{secondary or 'None'}

Original raw item context:
{raw_context or 'None'}

Supplied source links (preserve these URLs exactly):
{link_lines or 'None'}
"""


def split_title(text: str) -> tuple[str, str]:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    for idx, line in enumerate(lines[:5]):
        if line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip() or "Untitled summary"
            body = "\n".join(lines[:idx] + lines[idx + 1 :]).strip()
            return title, body or text.strip()
    return (lines[0][:160] if lines else "Untitled summary", text.strip())


def apply_summary_to_article(article: Any, result: SummaryResult) -> Any:
    fields = result.storage_fields()
    for key, value in fields.items():
        if hasattr(article, key):
            setattr(article, key, value)
    if isinstance(article, dict):
        article.update(fields)
    return article


def is_configured() -> bool:
    from app.ai.llm_client import is_configured as llm_is_configured

    return llm_is_configured()
