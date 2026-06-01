"""Telethon user-session collector plus shared async DB ingestion helpers."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Document, RawItem, RawItemLink, Source
from app.preprocessing.parse import ParsedDocument, content_hash
from app.preprocessing.urls import domain_from_url, extract_urls, normalize_url, prepare_url

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]
try:
    from telethon import TelegramClient
except Exception:  # pragma: no cover
    TelegramClient = None  # type: ignore[assignment]


def is_configured() -> bool:
    s = get_settings()
    return TelegramClient is not None and bool(s.telegram_api_id and s.telegram_api_hash)


def load_source_config() -> dict[str, Any]:
    path = get_settings().source_config_path
    if yaml is None or not Path(path).exists():
        return {}
    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _hash(text: str | None) -> str | None:
    return content_hash(text)


async def upsert_source(
    session: AsyncSession,
    *,
    source_type: str,
    name: str,
    url: str | None = None,
    identifier: str | None = None,
    config: dict[str, Any] | None = None,
    active: bool = True,
) -> Source:
    lookup_identifier = identifier or url or name
    result = await session.execute(select(Source).where(Source.source_type == source_type, Source.identifier == lookup_identifier))
    source = result.scalar_one_or_none()
    if source is None:
        try:
            async with session.begin_nested():
                source = Source(source_type=source_type, name=name, url=url, identifier=lookup_identifier, config_json=config or {}, active=active)
                session.add(source)
                await session.flush()
        except IntegrityError:
            result = await session.execute(select(Source).where(Source.source_type == source_type, Source.identifier == lookup_identifier))
            source = result.scalar_one()
    else:
        source.name = name or source.name
        source.url = url or source.url
        source.config_json = config or source.config_json
        source.active = active
    return source


async def upsert_raw_item(
    session: AsyncSession,
    *,
    source: Source | None,
    external_id: str | None,
    title: str | None = None,
    raw_text: str | None = None,
    raw_html: str | None = None,
    original_url: str | None = None,
    published_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    status: str = "new",
) -> RawItem:
    item = None
    if source is not None and external_id:
        result = await session.execute(select(RawItem).where(RawItem.source_id == source.id, RawItem.external_id == external_id))
        item = result.scalar_one_or_none()
    inserted = False
    if item is None:
        try:
            async with session.begin_nested():
                item = RawItem(source_id=source.id if source else None, external_id=external_id)
                session.add(item)
                await session.flush()
                inserted = True
        except IntegrityError:
            if source is not None and external_id:
                result = await session.execute(select(RawItem).where(RawItem.source_id == source.id, RawItem.external_id == external_id))
                item = result.scalar_one()
            else:
                raise
    item.title = title or item.title
    item.raw_text = raw_text
    item.raw_html = raw_html
    item.original_url = original_url
    item.published_at = published_at
    item.content_hash = _hash("\n".join(x for x in [title, raw_text] if x))
    item.metadata_json = metadata or {}
    # Scheduled collectors must not reset already processed/rejected/duplicate rows back to "new".
    # Explicit non-default statuses are still honored for callers that intentionally retry/override.
    if inserted or status != "new" or item.status == "new":
        item.status = status
    await session.flush()
    return item


async def add_raw_item_links(session: AsyncSession, raw_item: RawItem, urls: Iterable[str], *, primary_url: str | None = None) -> list[RawItemLink]:
    created: list[RawItemLink] = []
    seen: set[str] = set()
    for pos, url in enumerate(urls):
        normalized = prepare_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        existing = await session.execute(select(RawItemLink).where(RawItemLink.raw_item_id == raw_item.id, RawItemLink.normalized_url == normalized))
        link = existing.scalar_one_or_none()
        if link is None:
            link = RawItemLink(
                raw_item_id=raw_item.id,
                url=url,
                normalized_url=normalized,
                domain=domain_from_url(normalized),
                position=pos,
                is_primary=bool(primary_url and normalize_url(primary_url) == normalized),
            )
            session.add(link)
            created.append(link)
    await session.flush()
    return created


async def upsert_document(
    session: AsyncSession,
    parsed: ParsedDocument,
    *,
    raw_item: RawItem | None = None,
    source_link: RawItemLink | None = None,
    root_source_url: str | None = None,
    trust_level: str | None = None,
    source_role: str | None = None,
    rejection_reason: str | None = None,
) -> Document:
    canonical = parsed.canonical_url or normalize_url(parsed.url)
    result = await session.execute(select(Document).where(Document.canonical_url == canonical, Document.raw_item_id == (raw_item.id if raw_item else None)))
    doc = result.scalar_one_or_none()
    if doc is None:
        doc = Document(url=parsed.url, canonical_url=canonical, raw_item_id=raw_item.id if raw_item else None, source_link_id=source_link.id if source_link else None)
        session.add(doc)
    doc.root_source_url = root_source_url
    doc.domain = parsed.domain or domain_from_url(canonical)
    doc.title = parsed.title
    doc.cleaned_text = parsed.cleaned_text
    doc.html = parsed.html
    doc.language = getattr(parsed, "language", None)
    doc.published_at = parsed.published_at
    doc.author = parsed.author
    doc.content_hash = parsed.content_hash
    doc.extraction_method = parsed.extraction_method
    doc.trust_level = trust_level
    doc.source_role = source_role
    doc.is_root_source = bool(root_source_url and normalize_url(root_source_url) == canonical)
    doc.rejection_reason = rejection_reason
    doc.metadata_json = parsed.metadata
    await session.flush()
    return doc


def message_to_payload(message: Any) -> dict[str, Any]:
    text = getattr(message, "message", None) or getattr(message, "text", None) or ""
    urls = extract_urls(text)
    external_id = str(getattr(message, "id", hashlib.sha1(text.encode()).hexdigest()))
    return {
        "external_id": external_id,
        "title": text.splitlines()[0][:300] if text else None,
        "raw_text": text,
        "published_at": getattr(message, "date", None) or datetime.now(timezone.utc),
        "urls": urls,
        "metadata": {"telegram_message_id": external_id},
    }


async def collect_telegram_channels(limit: int = 50) -> int:
    if not is_configured():
        return 0
    s = get_settings()
    count = 0
    from app.db.session import AsyncSessionLocal

    async with TelegramClient(str(s.telegram_user_session_path), int(s.telegram_api_id), s.telegram_api_hash) as client:  # type: ignore[misc]
        async with AsyncSessionLocal() as session:
            for cfg in load_source_config().get("telegram") or []:
                if cfg.get("active", True) is False:
                    continue
                identifier = cfg.get("identifier") or cfg.get("url") or cfg.get("name")
                source = await upsert_source(session, source_type="telegram", name=cfg.get("name") or str(identifier), identifier=str(identifier), config=cfg)
                async for msg in client.iter_messages(identifier, limit=cfg.get("limit", limit)):
                    payload = message_to_payload(msg)
                    item = await upsert_raw_item(session, source=source, **{k: v for k, v in payload.items() if k != "urls"})
                    await add_raw_item_links(session, item, payload["urls"])
                    count += 1
            await session.commit()
    return count
