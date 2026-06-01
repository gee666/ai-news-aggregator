from typing import Any

from sqlalchemy import desc, or_, select

from app.config import get_settings
from app.db.models import RawItem, Source, StoryCluster, Summary
from app.db.session import AsyncSessionLocal


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.telegram_bot_token and settings.telegram_owner_chat_id)


def is_owner(chat_id: int | str | None) -> bool:
    owner = get_settings().telegram_owner_chat_id
    return bool(owner and chat_id is not None and str(chat_id) == str(owner))


def _dt(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _summary(summary: Summary) -> dict[str, Any]:
    return {
        "id": str(summary.id),
        "summary_title": summary.summary_title,
        "summary_text": summary.summary_text,
        "source_links_json": summary.source_links_json,
        "dt_created": _dt(summary.dt_created),
    }


async def latest(limit: int = 5) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(select(Summary).order_by(desc(Summary.dt_created)).limit(limit))
        return [_summary(row) for row in rows]


async def digest(limit: int = 10) -> list[dict[str, Any]]:
    return await latest(limit)


async def search(query: str, limit: int = 5) -> dict[str, Any]:
    pattern = f"%{query}%"
    async with AsyncSessionLocal() as session:
        summaries = await session.scalars(
            select(Summary)
            .where(or_(Summary.summary_title.ilike(pattern), Summary.summary_text.ilike(pattern)))
            .order_by(desc(Summary.dt_created))
            .limit(limit)
        )
        clusters = await session.scalars(
            select(StoryCluster)
            .where(StoryCluster.title.ilike(pattern))
            .order_by(desc(StoryCluster.dt_created))
            .limit(limit)
        )
        return {
            "summaries": [_summary(row) for row in summaries],
            "clusters": [{"id": str(row.id), "title": row.title, "status": row.status} for row in clusters],
        }


async def submit(text: str) -> str:
    url = text if text.startswith(("http://", "https://")) else None
    async with AsyncSessionLocal() as session:
        item = RawItem(
            source_id=None,
            title=None,
            raw_text=text,
            original_url=url,
            metadata_json={"submitted_via": "telegram_bot"},
            status="new",
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return str(item.id)


async def sources(limit: int = 50) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(select(Source).order_by(Source.name).limit(limit))
        return [
            {
                "id": str(row.id),
                "source_type": row.source_type,
                "name": row.name,
                "identifier": row.identifier,
                "url": row.url,
                "active": row.active,
            }
            for row in rows
        ]


async def status() -> dict[str, Any]:
    return {
        "bot_configured": is_configured(),
        "owner_configured": bool(get_settings().telegram_owner_chat_id),
        "database": "configured",
    }
