"""Fetch/parse trusted source documents reachable from raw item links."""
from __future__ import annotations

from collections import deque
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.collectors.telegram_user import upsert_document
from app.db.models import RawItem, RawItemLink
from app.preprocessing.fetch import fetch_url
from app.preprocessing.language import detect_language
from app.preprocessing.parse import ParsedDocument, parse_html
from app.preprocessing.trust import classify_url, load_trusted_social_accounts
from app.preprocessing.urls import is_forbidden_url, normalize_url, prepare_url
from urllib.parse import urlsplit


def is_configured() -> bool:
    return True


async def discover_sources_for_raw_item(session: AsyncSession, raw_item: RawItem, *, max_depth: int | None = None) -> int:
    settings = get_settings()
    max_depth = settings.max_link_depth if max_depth is None else max_depth
    links = (await session.execute(select(RawItemLink).where(RawItemLink.raw_item_id == raw_item.id))).scalars().all()
    queue = deque((link.normalized_url, 0, link) for link in links)
    seen: set[str] = set()
    saved = 0
    while queue:
        url, depth, source_link = queue.popleft()
        url = prepare_url(url)
        if url in seen or depth > max_depth:
            continue
        seen.add(url)
        verdict = is_forbidden_url(url, load_trusted_social_accounts())
        trust_level, rejection = classify_url(url)
        if not verdict.allowed or rejection or (depth > 0 and trust_level == "untrusted"):
            parsed = ParsedDocument(url=url, canonical_url=normalize_url(url))
            await upsert_document(session, parsed, raw_item=raw_item, source_link=source_link, root_source_url=links[0].normalized_url if links else url, trust_level=trust_level, rejection_reason=verdict.reason or rejection or "untrusted_discovered_link")
            saved += 1
            continue
        fetched = await fetch_url(url)
        if not fetched.ok:
            parsed = ParsedDocument(url=url, canonical_url=normalize_url(url), metadata={"fetch_error": fetched.error, "status_code": fetched.status_code})
            await upsert_document(session, parsed, raw_item=raw_item, source_link=source_link, root_source_url=links[0].normalized_url if links else url, trust_level=trust_level, rejection_reason=fetched.error or "fetch_failed")
            saved += 1
            continue
        final_url = fetched.final_url or url
        final_verdict = is_forbidden_url(final_url, load_trusted_social_accounts())
        trust_level, final_rejection = classify_url(final_url)
        if not final_verdict.allowed or final_rejection:
            parsed = ParsedDocument(url=final_url, canonical_url=normalize_url(final_url))
            await upsert_document(session, parsed, raw_item=raw_item, source_link=source_link, root_source_url=links[0].normalized_url if links else url, trust_level=trust_level, rejection_reason=final_verdict.reason or final_rejection)
            saved += 1
            continue
        parsed = parse_html(fetched.text, final_url)
        parsed.language = detect_language(parsed.cleaned_text)
        rejection = None
        if settings.require_english and parsed.language not in {"en", None}:
            rejection = "non_english"
        await upsert_document(session, parsed, raw_item=raw_item, source_link=source_link, root_source_url=links[0].normalized_url if links else url, trust_level=trust_level, source_role="root" if depth == 0 else "discovered", rejection_reason=rejection)
        saved += 1
        if depth < max_depth:
            for child in parsed.links[:50]:
                if urlsplit(child).scheme.lower() not in {"http", "https", ""}:
                    continue
                child_url = prepare_url(child, fetched.final_url or url)
                child_trust, child_rejection = classify_url(child_url)
                if child_url not in seen and child_trust != "untrusted" and not child_rejection:
                    queue.append((child_url, depth + 1, source_link))
    return saved


async def discover_sources(session: AsyncSession, raw_items: Iterable[RawItem], *, max_depth: int | None = None) -> int:
    total = 0
    for item in raw_items:
        total += await discover_sources_for_raw_item(session, item, max_depth=max_depth)
    return total
