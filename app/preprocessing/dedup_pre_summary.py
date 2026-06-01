"""Pre-summary duplicate detection for raw items and parsed documents."""
from __future__ import annotations

import hashlib
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, RawItem, RawItemLink
from app.preprocessing.urls import domain_from_url, normalize_url, root_domain


def is_configured() -> bool:
    return True


def bundle_key(*values: str | None) -> str | None:
    present = [v for v in values if v]
    if not present:
        return None
    return hashlib.sha256("|".join(present).encode("utf-8")).hexdigest()


async def mark_duplicate(session: AsyncSession, duplicate: RawItem, primary: RawItem, reason: str) -> None:
    duplicate.status = "duplicate"
    duplicate.duplicate_of_raw_item_id = primary.id
    duplicate.rejection_reason = reason


async def dedup_raw_items(session: AsyncSession, raw_items: Iterable[RawItem] | None = None) -> int:
    """Mark duplicates by external id, canonical URLs, root domains, content hashes, and bundles."""
    items = list(raw_items) if raw_items is not None else list((await session.execute(select(RawItem).where(RawItem.status != "duplicate"))).scalars())
    by_key: dict[tuple[str, str], RawItem] = {}
    duplicates = 0

    for item in sorted(items, key=lambda i: (i.published_at or i.collected_at, i.id)):
        keys: list[tuple[str, str]] = []
        if item.source_id and item.external_id:
            keys.append(("external", f"{item.source_id}:{item.external_id}"))
        if item.content_hash:
            keys.append(("content", item.content_hash))

        links = (await session.execute(select(RawItemLink).where(RawItemLink.raw_item_id == item.id))).scalars().all()
        for link in links:
            canonical = normalize_url(link.normalized_url or link.url)
            keys.append(("url", canonical))
            root = root_domain(link.domain or domain_from_url(canonical))
            if root and item.content_hash:
                keys.append(("root_content", f"{root}:{item.content_hash}"))

        docs = (await session.execute(select(Document).where(Document.raw_item_id == item.id))).scalars().all()
        trusted_domains = []
        for doc in docs:
            if doc.canonical_url:
                keys.append(("doc_url", normalize_url(doc.canonical_url)))
            if doc.content_hash:
                keys.append(("doc_content", doc.content_hash))
            if doc.domain and doc.trust_level in {"primary", "trusted", "official"}:
                trusted_domains.append(root_domain(doc.domain) or doc.domain)
        source_bundle = bundle_key(item.content_hash, *sorted(set(trusted_domains)))
        if source_bundle:
            keys.append(("source_bundle", source_bundle))

        primary = None
        reason = None
        for key in keys:
            if key in by_key:
                primary = by_key[key]
                reason = f"duplicate_{key[0]}"
                break
        if primary is not None:
            await mark_duplicate(session, item, primary, reason or "duplicate")
            duplicates += 1
        else:
            for key in keys:
                by_key.setdefault(key, item)
    await session.flush()
    return duplicates
