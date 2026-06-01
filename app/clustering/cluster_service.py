"""Service for assigning summaries to hybrid story clusters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import EmbeddingService, store_embedding
from app.clustering.candidate_search import Candidate, find_similar_summaries
from app.clustering.story_matcher import StoryMatcher
from app.db.models import RelatedStory, StoryCluster, StoryClusterItem


class ClusterService:
    def __init__(self, embeddings: EmbeddingService | None = None, matcher: StoryMatcher | None = None) -> None:
        self.embeddings = embeddings or EmbeddingService()
        self.matcher = matcher or StoryMatcher()

    async def cluster_summary(
        self,
        session: AsyncSession,
        *,
        summary_id: Any,
        summary_title: str,
        summary_text: str,
        document_id: Any | None = None,
        raw_item_id: Any | None = None,
        canonical_url: str | None = None,
        root_source_url: str | None = None,
        content_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StoryCluster:
        await self._advisory_lock(session, f"summary:{summary_id}")
        existing = await self._existing_cluster(session, summary_id)
        if existing is not None:
            return existing

        lock_key = deterministic_lock_key(canonical_url, root_source_url, content_hash)
        if lock_key:
            if not await self._try_advisory_lock(session, lock_key):
                raise RuntimeError(f"cluster lock is busy for {lock_key}; retry this summary later")
            existing = await self._existing_cluster(session, summary_id)
            if existing is not None:
                return existing

        text = f"{summary_title}\n\n{summary_text}"
        vector = self.embeddings.embed(text)
        candidates = await find_similar_summaries(session, vector, exclude_summary_id=summary_id)
        incoming = {
            "summary_id": str(summary_id),
            "title": summary_title,
            "summary_text": summary_text,
            "canonical_url": canonical_url,
            "root_source_url": root_source_url,
            "content_hash": content_hash,
            **(metadata or {}),
        }
        for candidate in candidates:
            decision = await self.matcher.match(incoming, candidate)
            if decision.should_merge:
                if candidate.cluster_id:
                    await self._add_item(
                        session,
                        cluster_id=candidate.cluster_id,
                        summary_id=summary_id,
                        document_id=document_id,
                        raw_item_id=raw_item_id,
                        similarity_score=candidate.similarity,
                        match_confidence=decision.confidence,
                        match_reason=decision.reason,
                    )
                    await store_embedding(session, target_type="summary", target_id=summary_id, text=text, vector=vector)
                    return await session.get(StoryCluster, candidate.cluster_id)  # type: ignore[return-value]
                candidate_lock = f"summary:{candidate.summary_id}"
                if not await self._try_advisory_lock(session, candidate_lock):
                    raise RuntimeError(f"cluster lock is busy for {candidate_lock}; retry this summary later")
                existing_candidate_cluster = await self._existing_cluster(session, candidate.summary_id)
                if existing_candidate_cluster is not None:
                    await self._add_item(
                        session,
                        cluster_id=existing_candidate_cluster.id,
                        summary_id=summary_id,
                        document_id=document_id,
                        raw_item_id=raw_item_id,
                        similarity_score=candidate.similarity,
                        match_confidence=decision.confidence,
                        match_reason=decision.reason,
                    )
                    await store_embedding(session, target_type="summary", target_id=summary_id, text=text, vector=vector)
                    return existing_candidate_cluster
                cluster = await self._create_backfilled_cluster(
                    session,
                    candidate=candidate,
                    summary_id=summary_id,
                    summary_title=summary_title,
                    document_id=document_id,
                    raw_item_id=raw_item_id,
                    metadata=metadata,
                    similarity_score=candidate.similarity,
                    match_confidence=decision.confidence,
                    match_reason=decision.reason,
                )
                await store_embedding(session, target_type="summary", target_id=summary_id, text=text, vector=vector)
                return cluster
            if decision.relation_type == "related" and candidate.cluster_id:
                # If no merge is found later, relation is recorded after new cluster creation.
                incoming.setdefault("related_cluster_ids", []).append((candidate.cluster_id, decision.confidence, decision.reason))

        cluster = StoryCluster(title=summary_title, metadata_json=metadata or {})
        session.add(cluster)
        await session.flush()
        await self._add_item(
            session,
            cluster_id=cluster.id,
            summary_id=summary_id,
            document_id=document_id,
            raw_item_id=raw_item_id,
            similarity_score=None,
            match_confidence=1.0,
            match_reason="new_cluster",
            is_primary=True,
        )
        for related_id, confidence, reason in incoming.get("related_cluster_ids", []):
            session.add(
                RelatedStory(
                    cluster_id_a=cluster.id,
                    cluster_id_b=related_id,
                    relation_type="same_topic",
                    confidence=confidence,
                    reason=reason,
                )
            )
        await store_embedding(session, target_type="summary", target_id=summary_id, text=text, vector=vector)
        return cluster

    async def _create_backfilled_cluster(
        self,
        session: AsyncSession,
        *,
        candidate: Candidate,
        summary_id: Any,
        summary_title: str,
        document_id: Any | None,
        raw_item_id: Any | None,
        metadata: dict[str, Any] | None,
        similarity_score: float,
        match_confidence: float,
        match_reason: str,
    ) -> StoryCluster:
        cluster = StoryCluster(title=candidate.title or summary_title, metadata_json=metadata or {})
        session.add(cluster)
        await session.flush()
        await self._add_item(
            session,
            cluster_id=cluster.id,
            summary_id=candidate.summary_id,
            document_id=candidate.document_id,
            raw_item_id=candidate.raw_item_id,
            similarity_score=similarity_score,
            match_confidence=match_confidence,
            match_reason="backfilled_cluster_candidate",
            is_primary=True,
        )
        await self._add_item(
            session,
            cluster_id=cluster.id,
            summary_id=summary_id,
            document_id=document_id,
            raw_item_id=raw_item_id,
            similarity_score=similarity_score,
            match_confidence=match_confidence,
            match_reason=match_reason,
        )
        return cluster

    async def _existing_cluster(self, session: AsyncSession, summary_id: Any) -> StoryCluster | None:
        result = await session.execute(select(StoryClusterItem).where(StoryClusterItem.summary_id == summary_id).limit(1))
        item = result.scalar_one_or_none()
        if item is None:
            return None
        return await session.get(StoryCluster, item.cluster_id)

    async def _advisory_lock(self, session: AsyncSession, key: str) -> None:
        await session.execute(sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})

    async def _try_advisory_lock(self, session: AsyncSession, key: str) -> bool:
        result = await session.execute(sql_text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
        return bool(result.scalar_one())

    async def _add_item(self, session: AsyncSession, **kwargs: Any) -> StoryClusterItem:
        item = StoryClusterItem(**kwargs)
        session.add(item)
        await session.flush()
        return item


def deterministic_lock_key(
    canonical_url: str | None = None,
    root_source_url: str | None = None,
    content_hash: str | None = None,
) -> str | None:
    if content_hash:
        return f"content:{content_hash}"
    if canonical_url:
        return f"url:{canonical_url}"
    if root_source_url:
        return f"root:{root_source_url}"
    return None


def is_configured() -> bool:
    return True
