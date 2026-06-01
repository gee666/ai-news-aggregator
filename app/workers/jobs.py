"""Worker job registry and MVP job implementations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Document, Embedding, RawItem, RawItemLink, StoryClusterItem, Summary, SummaryLink
from app.db.session import AsyncSessionLocal
from app.preprocessing.urls import extract_urls, normalize_url

JOB_NAMES = [
    "collect_telegram_channels",
    "collect_gmail_newsletters",
    "collect_rss_sources",
    "process_new_raw_items",
    "fetch_and_parse_links",
    "run_pre_summary_dedup",
    "summarize_ready_items",
    "embed_new_summaries",
    "cluster_new_summaries",
    "generate_or_update_cluster_summaries",
    "send_digest_to_telegram",
]

JobResult = dict[str, Any]
JobCallable = Callable[[], Awaitable[JobResult]]


def _result(job_name: str, detail: str, **extra: Any) -> JobResult:
    return {
        "job_name": job_name,
        "status": "completed",
        "detail": detail,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }


def _error(job_name: str, exc: Exception) -> JobResult:
    return {
        "job_name": job_name,
        "status": "error",
        "detail": f"{type(exc).__name__}: {exc}",
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }


async def collect_telegram_channels() -> JobResult:
    job = "collect_telegram_channels"
    try:
        from app.collectors.telegram_user import collect_telegram_channels as collect, is_configured

        if not is_configured():
            return _result(job, "Telethon credentials not configured", collected=0)
        count = await collect()
        return _result(job, f"collected {count} Telegram raw items", collected=count)
    except Exception as exc:
        return _error(job, exc)


async def collect_gmail_newsletters() -> JobResult:
    job = "collect_gmail_newsletters"
    try:
        from app.collectors.gmail import collect_gmail_newsletters as collect, is_configured

        if not is_configured():
            return _result(job, "Gmail OAuth not configured", collected=0)
        count = await collect()
        return _result(job, f"collected {count} Gmail raw items", collected=count)
    except Exception as exc:
        return _error(job, exc)


async def collect_rss_sources() -> JobResult:
    job = "collect_rss_sources"
    try:
        from app.collectors.rss import collect_rss_sources as collect, is_configured

        if not is_configured():
            return _result(job, "feedparser not installed", collected=0)
        count = await collect()
        return _result(job, f"collected {count} RSS raw items", collected=count)
    except Exception as exc:
        return _error(job, exc)


async def process_new_raw_items() -> JobResult:
    """Extract first-class links from newly collected raw items."""
    job = "process_new_raw_items"
    try:
        from app.collectors.telegram_user import add_raw_item_links

        processed = rejected = links_created = 0
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(RawItem).where(RawItem.status == "new"))).scalars().all()
            for item in rows:
                urls: list[str] = []
                if item.original_url:
                    urls.append(item.original_url)
                urls.extend(extract_urls("\n".join(x for x in [item.raw_text, item.raw_html] if x)))
                created = await add_raw_item_links(session, item, urls, primary_url=item.original_url or (urls[0] if urls else None))
                links_created += len(created)
                processed += 1
                if urls:
                    item.status = "pending_fetch"
                    item.rejection_reason = None
                else:
                    item.status = "rejected_no_links"
                    item.rejection_reason = "no_urls_extracted"
                    rejected += 1
            await session.commit()
        return _result(job, f"processed {processed} raw items", processed=processed, links_created=links_created, rejected=rejected)
    except Exception as exc:
        return _error(job, exc)


async def fetch_and_parse_links() -> JobResult:
    """Fetch raw links, parse documents, validate language/trust, set raw item readiness."""
    job = "fetch_and_parse_links"
    try:
        from app.preprocessing.source_discovery import discover_sources_for_raw_item

        settings = get_settings()
        processed = docs_before_total = docs_after_total = ready = rejected = 0
        async with AsyncSessionLocal() as session:
            raw_items = (
                await session.execute(
                    select(RawItem).where(RawItem.status.in_(["pending_fetch", "retry_fetch"]))
                )
            ).scalars().all()
            for item in raw_items:
                link_count = (
                    await session.execute(select(RawItemLink).where(RawItemLink.raw_item_id == item.id))
                ).scalars().all()
                if not link_count:
                    item.status = "rejected_no_links"
                    item.rejection_reason = "no_links_to_fetch"
                    rejected += 1
                    continue
                docs_before = len((await session.execute(select(Document).where(Document.raw_item_id == item.id))).scalars().all())
                await discover_sources_for_raw_item(session, item)
                docs = (await session.execute(select(Document).where(Document.raw_item_id == item.id))).scalars().all()
                docs_after = len(docs)
                docs_before_total += docs_before
                docs_after_total += docs_after

                # Update link status from associated documents.
                for link in link_count:
                    link_docs = [doc for doc in docs if doc.source_link_id == link.id]
                    if not link_docs:
                        link.status = "no_document"
                    elif any(not doc.rejection_reason for doc in link_docs):
                        link.status = "parsed"
                    else:
                        link.status = "rejected"

                trusted_docs = [
                    doc
                    for doc in docs
                    if not doc.rejection_reason
                    and doc.cleaned_text
                    and (doc.language in {"en", None} or not settings.require_english)
                    and doc.trust_level in {"primary", "trusted", "official"}
                ]
                if len(trusted_docs) >= settings.min_trusted_documents:
                    item.status = "ready_for_summary"
                    item.rejection_reason = None
                    ready += 1
                else:
                    item.status = "rejected_no_trusted_source"
                    item.rejection_reason = "no_trusted_english_document"
                    rejected += 1
                processed += 1
            await session.commit()
        return _result(
            job,
            f"processed {processed} raw items; {ready} ready",
            processed=processed,
            documents_created=max(0, docs_after_total - docs_before_total),
            ready=ready,
            rejected=rejected,
        )
    except Exception as exc:
        return _error(job, exc)


async def run_pre_summary_dedup() -> JobResult:
    job = "run_pre_summary_dedup"
    try:
        from app.preprocessing.dedup_pre_summary import dedup_raw_items

        async with AsyncSessionLocal() as session:
            duplicates = await dedup_raw_items(session)
            await session.commit()
        return _result(job, f"marked {duplicates} duplicates", duplicates=duplicates)
    except Exception as exc:
        return _error(job, exc)


async def summarize_ready_items() -> JobResult:
    job = "summarize_ready_items"
    try:
        from app.ai.summarizer import SourceLink, Summarizer, is_configured

        if not is_configured():
            return _result(job, "LLM OAuth/client not configured; skipped", summarized=0, skipped="llm_not_configured")

        summarized = skipped = 0
        async with AsyncSessionLocal() as session:
            raw_items = (await session.execute(select(RawItem).where(RawItem.status == "ready_for_summary"))).scalars().all()
            summarizer = Summarizer()
            for item in raw_items:
                existing = (
                    await session.execute(select(Summary).where(Summary.target_type == "raw_item", Summary.target_id == item.id))
                ).scalar_one_or_none()
                if existing:
                    item.status = "summarized"
                    skipped += 1
                    continue
                docs = (await session.execute(select(Document).where(Document.raw_item_id == item.id))).scalars().all()
                trusted_docs = [
                    d for d in docs if not d.rejection_reason and d.cleaned_text and d.trust_level in {"primary", "trusted", "official"}
                ]
                if not trusted_docs:
                    item.status = "rejected_no_trusted_source"
                    item.rejection_reason = "no_trusted_document_for_summary"
                    skipped += 1
                    continue
                root = next((d for d in trusted_docs if d.source_role == "root" or d.is_root_source), trusted_docs[0])
                secondary = [d.cleaned_text or "" for d in trusted_docs if d.id != root.id][:5]
                links = [
                    SourceLink(
                        url=d.canonical_url or d.url,
                        normalized_url=normalize_url(d.canonical_url or d.url),
                        canonical_url=d.canonical_url,
                        domain=d.domain,
                        link_type=d.source_role or "source",
                        trust_level=d.trust_level,
                        title=d.title,
                    )
                    for d in trusted_docs
                ]
                result = await summarizer.summarize_bundle(
                    root_text=root.cleaned_text or "",
                    secondary_texts=secondary,
                    raw_context=item.raw_text,
                    links=links,
                )
                summary = Summary(
                    target_type="raw_item",
                    target_id=item.id,
                    summary_title=result.summary_title,
                    summary_text=result.summary_text,
                    summary_template_version=result.summary_template_version,
                    model_name=result.model_name,
                    prompt_version=result.prompt_version,
                    source_links_json=[link.to_json() for link in links],
                    metadata_json={"root_document_id": str(root.id), "raw_item_id": str(item.id)},
                )
                session.add(summary)
                await session.flush()
                for link in links:
                    session.add(
                        SummaryLink(
                            summary_id=summary.id,
                            url=link.url,
                            normalized_url=link.normalized_url,
                            canonical_url=link.canonical_url,
                            domain=link.domain,
                            link_type=link.link_type,
                            trust_level=link.trust_level,
                        )
                    )
                item.status = "summarized"
                summarized += 1
            await session.commit()
        return _result(job, f"created {summarized} summaries", summarized=summarized, skipped=skipped)
    except Exception as exc:
        return _error(job, exc)


async def embed_new_summaries() -> JobResult:
    job = "embed_new_summaries"
    try:
        from app.ai.embeddings import EmbeddingService, store_embedding

        embedded = skipped = 0
        async with AsyncSessionLocal() as session:
            summaries = (await session.execute(select(Summary))).scalars().all()
            service: EmbeddingService | None = None
            for summary in summaries:
                existing = (
                    await session.execute(
                        select(Embedding).where(Embedding.target_type == "summary", Embedding.target_id == summary.id)
                    )
                ).scalar_one_or_none()
                if existing:
                    skipped += 1
                    continue
                service = service or EmbeddingService()
                text = f"{summary.summary_title}\n\n{summary.summary_text}"
                vector = service.embed(text)
                await store_embedding(session, target_type="summary", target_id=summary.id, text=text, vector=vector)
                embedded += 1
            await session.commit()
        return _result(job, f"embedded {embedded} summaries", embedded=embedded, skipped=skipped)
    except Exception as exc:
        return _error(job, exc)


async def cluster_new_summaries() -> JobResult:
    job = "cluster_new_summaries"
    try:
        from app.clustering.cluster_service import ClusterService

        clustered = skipped = 0
        async with AsyncSessionLocal() as session:
            summaries = (await session.execute(select(Summary))).scalars().all()
            service: ClusterService | None = None
            for summary in summaries:
                existing = (
                    await session.execute(select(StoryClusterItem).where(StoryClusterItem.summary_id == summary.id))
                ).scalar_one_or_none()
                if existing:
                    skipped += 1
                    continue
                docs = []
                raw_item_id = summary.target_id if summary.target_type == "raw_item" else None
                if raw_item_id:
                    docs = (await session.execute(select(Document).where(Document.raw_item_id == raw_item_id))).scalars().all()
                root = next((d for d in docs if d.source_role == "root" or d.is_root_source), docs[0] if docs else None)
                service = service or ClusterService()
                await service.cluster_summary(
                    session,
                    summary_id=summary.id,
                    summary_title=summary.summary_title,
                    summary_text=summary.summary_text,
                    document_id=root.id if root else None,
                    raw_item_id=raw_item_id,
                    canonical_url=root.canonical_url if root else None,
                    root_source_url=root.root_source_url if root else None,
                    content_hash=root.content_hash if root else None,
                    metadata=summary.metadata_json,
                )
                clustered += 1
            await session.commit()
        return _result(job, f"clustered {clustered} summaries", clustered=clustered, skipped=skipped)
    except Exception as exc:
        return _error(job, exc)


async def generate_or_update_cluster_summaries() -> JobResult:
    # Combined cluster summaries require an LLM and a policy for digest cadence. MVP keeps the
    # individual trusted summaries and records clusters; this job is deliberately safe/idempotent.
    return _result("generate_or_update_cluster_summaries", "combined cluster summary generation deferred", updated=0)


async def send_digest_to_telegram() -> JobResult:
    job = "send_digest_to_telegram"
    try:
        from app.bot.telegram_bot import send_digest_to_owner

        sent = await send_digest_to_owner()
        return _result(job, "digest sent" if sent else "bot not configured", sent=sent)
    except Exception as exc:
        return _error(job, exc)


JOBS: dict[str, JobCallable] = {
    "collect_telegram_channels": collect_telegram_channels,
    "collect_gmail_newsletters": collect_gmail_newsletters,
    "collect_rss_sources": collect_rss_sources,
    "process_new_raw_items": process_new_raw_items,
    "fetch_and_parse_links": fetch_and_parse_links,
    "run_pre_summary_dedup": run_pre_summary_dedup,
    "summarize_ready_items": summarize_ready_items,
    "embed_new_summaries": embed_new_summaries,
    "cluster_new_summaries": cluster_new_summaries,
    "generate_or_update_cluster_summaries": generate_or_update_cluster_summaries,
    "send_digest_to_telegram": send_digest_to_telegram,
}


async def run_once(job_name: str) -> JobResult:
    try:
        job = JOBS[job_name]
    except KeyError as exc:
        raise ValueError(f"Unknown job: {job_name}") from exc
    return await job()
