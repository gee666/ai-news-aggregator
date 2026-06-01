"""HTML/article parsing with graceful optional dependency fallbacks."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from app.preprocessing.urls import domain_from_url, extract_urls, normalize_url

try:
    import trafilatura
except Exception:  # pragma: no cover
    trafilatura = None  # type: ignore[assignment]
try:
    from readability import Document as ReadabilityDocument
except Exception:  # pragma: no cover
    ReadabilityDocument = None  # type: ignore[assignment]
try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore[assignment]


@dataclass(slots=True)
class ParsedDocument:
    url: str
    canonical_url: str | None = None
    domain: str | None = None
    title: str | None = None
    cleaned_text: str | None = None
    html: str | None = None
    language: str | None = None
    published_at: datetime | None = None
    author: str | None = None
    content_hash: str | None = None
    extraction_method: str | None = None
    links: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def is_configured() -> bool:
    return any([trafilatura, ReadabilityDocument, BeautifulSoup])


def content_hash(text: str | None) -> str | None:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_html(html: str | None, url: str) -> ParsedDocument:
    html = html or ""
    canonical = normalize_url(url)
    title = None
    text = None
    author = None
    published = None
    method = "fallback"
    links = extract_urls(html)
    metadata: dict[str, Any] = {}

    if trafilatura is not None and html:
        try:
            extracted = trafilatura.extract(html, url=url, include_links=False, include_comments=False, output_format="txt")
            meta = trafilatura.extract_metadata(html, default_url=url)
            if extracted:
                text = extracted.strip()
                method = "trafilatura"
            if meta:
                title = getattr(meta, "title", None) or title
                author = getattr(meta, "author", None) or author
                canonical = normalize_url(getattr(meta, "url", None) or canonical)
                published = _parse_datetime(getattr(meta, "date", None))
                metadata["trafilatura"] = {"sitename": getattr(meta, "sitename", None)}
        except Exception as exc:
            metadata["trafilatura_error"] = str(exc)

    if not text and ReadabilityDocument is not None and html:
        try:
            doc = ReadabilityDocument(html)
            title = doc.short_title() or title
            summary_html = doc.summary(html_partial=True)
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", summary_html)).strip()
            method = "readability"
        except Exception as exc:
            metadata["readability_error"] = str(exc)

    if BeautifulSoup is not None and html:
        try:
            soup = BeautifulSoup(html, "html.parser")
            canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in v)
            if canonical_tag and canonical_tag.get("href"):
                canonical = normalize_url(urljoin(url, canonical_tag["href"]))
            title = title or (soup.title.get_text(" ", strip=True) if soup.title else None)
            author_tag = soup.find("meta", attrs={"name": "author"})
            author = author or (author_tag.get("content") if author_tag else None)
            date_tag = soup.find("meta", attrs={"property": "article:published_time"}) or soup.find("time")
            published = published or _parse_datetime((date_tag.get("content") or date_tag.get("datetime")) if date_tag else None)
            for a in soup.find_all("a", href=True):
                links.append(normalize_url(urljoin(url, a["href"])))
            if not text:
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                text = soup.get_text(" ", strip=True)
                method = "beautifulsoup"
        except Exception as exc:
            metadata["beautifulsoup_error"] = str(exc)

    text = re.sub(r"\s+", " ", text or "").strip() or None
    unique_links = list(dict.fromkeys(links))
    return ParsedDocument(
        url=url,
        canonical_url=canonical,
        domain=domain_from_url(canonical or url),
        title=title,
        cleaned_text=text,
        html=html,
        published_at=published,
        author=author,
        content_hash=content_hash(text),
        extraction_method=method,
        links=unique_links,
        metadata=metadata,
    )
