"""Manual Telegram bot submission ingestion helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.collectors.telegram_user import add_raw_item_links, upsert_raw_item, upsert_source
from app.preprocessing.urls import extract_urls


def is_configured() -> bool:
    return True


async def ingest_submission(
    text: str,
    *,
    submitter_id: str | int | None = None,
    message_id: str | int | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Persist a Telegram bot/manual submission and return the raw item id."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        source = await upsert_source(
            session,
            source_type="telegram_submission",
            name=f"Telegram submissions {submitter_id or 'unknown'}",
            identifier=str(submitter_id or "unknown"),
            config={"submitter_id": submitter_id},
        )
        external_id = str(message_id or f"submission:{submitter_id}:{hash(text)}")
        urls = extract_urls(text)
        item = await upsert_raw_item(
            session,
            source=source,
            external_id=external_id,
            title=(text.splitlines()[0][:300] if text else None),
            raw_text=text,
            published_at=datetime.now(timezone.utc),
            metadata={"submitter_id": submitter_id, "message_id": message_id, **(metadata or {})},
        )
        await add_raw_item_links(session, item, urls, primary_url=urls[0] if urls else None)
        await session.commit()
        return str(item.id)
