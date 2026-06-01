from html import escape
from typing import Any

TELEGRAM_MESSAGE_LIMIT = 3900


def split_telegram_html(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split formatted text conservatively under Telegram's 4096 char limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def format_summary(summary: dict[str, Any]) -> str:
    title = escape(str(summary.get("summary_title") or "Untitled"))
    text = escape(str(summary.get("summary_text") or ""))
    links = summary.get("source_links_json") or []
    rendered_links = []
    for link in links[:5]:
        url = link.get("url") if isinstance(link, dict) else None
        if url:
            rendered_links.append(f"• {escape(str(url))}")
    link_block = "\n" + "\n".join(rendered_links) if rendered_links else ""
    return f"<b>{title}</b>\n{text}{link_block}"


def format_digest(summaries: list[dict[str, Any]]) -> str:
    if not summaries:
        return "No summaries yet."
    parts = ["<b>Latest digest</b>"]
    for index, summary in enumerate(summaries, start=1):
        title = escape(str(summary.get("summary_title") or "Untitled"))
        text = escape(str(summary.get("summary_text") or ""))
        parts.append(f"{index}. <b>{title}</b>\n{text[:500]}")
    return "\n\n".join(parts)


def format_sources(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "No sources configured."
    return "\n".join(
        f"• {escape(str(source.get('name') or source.get('identifier') or 'Unnamed'))} "
        f"({escape(str(source.get('source_type') or 'unknown'))})"
        for source in sources
    )


def format_status(status: dict[str, Any]) -> str:
    return "\n".join(f"{escape(str(key))}: {escape(str(value))}" for key, value in status.items())
