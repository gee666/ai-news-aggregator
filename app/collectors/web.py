"""Simple configured web page collector."""
from __future__ import annotations

from datetime import datetime, timezone

from app.collectors.telegram_user import add_raw_item_links, load_source_config, upsert_raw_item, upsert_source
from app.preprocessing.fetch import fetch_url
from app.preprocessing.parse import parse_html


def is_configured() -> bool:
    return True


async def collect_web_sources() -> int:
    from app.db.session import AsyncSessionLocal

    count = 0
    async with AsyncSessionLocal() as session:
        for cfg in load_source_config().get("web") or []:
            if cfg.get("active", True) is False or not cfg.get("url"):
                continue
            source = await upsert_source(session, source_type="web", name=cfg.get("name") or cfg["url"], url=cfg["url"], identifier=cfg["url"], config=cfg)
            fetched = await fetch_url(cfg["url"])
            if not fetched.ok:
                continue
            parsed = parse_html(fetched.text, fetched.final_url or cfg["url"])
            item = await upsert_raw_item(
                session,
                source=source,
                external_id=parsed.canonical_url or cfg["url"],
                title=parsed.title,
                raw_text=parsed.cleaned_text,
                raw_html=fetched.text,
                original_url=cfg["url"],
                published_at=parsed.published_at or datetime.now(timezone.utc),
                metadata={"final_url": fetched.final_url, "status_code": fetched.status_code},
            )
            await add_raw_item_links(session, item, [parsed.canonical_url or cfg["url"], *parsed.links], primary_url=parsed.canonical_url or cfg["url"])
            count += 1
        await session.commit()
    return count
