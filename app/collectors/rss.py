"""RSS/Atom collector using configured feeds."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.collectors.telegram_user import add_raw_item_links, load_source_config, upsert_raw_item, upsert_source
from app.preprocessing.fetch import fetch_url
from app.preprocessing.urls import extract_urls

try:
    import feedparser
except Exception:  # pragma: no cover
    feedparser = None  # type: ignore[assignment]


def is_configured() -> bool:
    return feedparser is not None


def _entry_date(entry: Any) -> datetime | None:
    for key in ("published", "updated", "created"):
        value = entry.get(key) if hasattr(entry, "get") else None
        if value:
            try:
                return parsedate_to_datetime(value)
            except Exception:
                pass
    return None


async def collect_rss_sources() -> int:
    if feedparser is None:
        return 0
    from app.db.session import AsyncSessionLocal

    count = 0
    async with AsyncSessionLocal() as session:
        for cfg in load_source_config().get("rss") or []:
            if cfg.get("active", True) is False or not cfg.get("url"):
                continue
            source = await upsert_source(session, source_type="rss", name=cfg.get("name") or cfg["url"], url=cfg["url"], identifier=cfg["url"], config=cfg)
            fetched = await fetch_url(cfg["url"])
            if not fetched.ok:
                continue
            feed = feedparser.parse(fetched.content or fetched.text or "")
            for entry in feed.entries:
                link = entry.get("link")
                text = "\n".join(str(x or "") for x in [entry.get("title"), entry.get("summary"), entry.get("description")])
                urls = [link] if link else []
                urls.extend(extract_urls(text))
                item = await upsert_raw_item(
                    session,
                    source=source,
                    external_id=str(entry.get("id") or entry.get("guid") or link or hash(text)),
                    title=entry.get("title"),
                    raw_text=text.strip(),
                    raw_html=entry.get("summary") or entry.get("description"),
                    original_url=link,
                    published_at=_entry_date(entry) or datetime.now(timezone.utc),
                    metadata={"rss_entry": dict(entry)},
                )
                await add_raw_item_links(session, item, urls, primary_url=link)
                count += 1
        await session.commit()
    return count
