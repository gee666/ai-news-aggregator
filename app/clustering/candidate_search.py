"""pgvector candidate retrieval for summaries/clusters.

Embeddings are used only to retrieve candidates; final same-story decisions live
in story_matcher.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings


@dataclass(slots=True)
class Candidate:
    summary_id: Any
    cluster_id: Any | None
    document_id: Any | None
    raw_item_id: Any | None
    similarity: float
    title: str
    summary_text: str
    canonical_url: str | None = None
    root_source_url: str | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] | None = None


async def find_similar_summaries(
    session: AsyncSession,
    query_vector: list[float],
    *,
    limit: int = 20,
    min_similarity: float = 0.72,
    model_name: str | None = None,
    exclude_summary_id: Any | None = None,
) -> list[Candidate]:
    settings = get_settings()
    vector = "[" + ",".join(str(float(v)) for v in query_vector) + "]"
    sql = text(
        """
        SELECT
          s.id AS summary_id,
          sci.cluster_id AS cluster_id,
          sci.document_id AS document_id,
          sci.raw_item_id AS raw_item_id,
          1 - (e.embedding <=> CAST(:query_vector AS vector)) AS similarity,
          s.summary_title AS title,
          s.summary_text AS summary_text,
          d.canonical_url AS canonical_url,
          d.root_source_url AS root_source_url,
          d.content_hash AS content_hash,
          s.metadata_json AS metadata
        FROM embeddings e
        JOIN summaries s ON s.id = e.target_id AND e.target_type = 'summary'
        LEFT JOIN story_cluster_items sci ON sci.summary_id = s.id
        LEFT JOIN documents d ON d.id = sci.document_id
        WHERE e.model_name = :model_name
          AND (:exclude_summary_id IS NULL OR s.id <> CAST(:exclude_summary_id AS uuid))
          AND (1 - (e.embedding <=> CAST(:query_vector AS vector))) >= :min_similarity
        ORDER BY e.embedding <=> CAST(:query_vector AS vector)
        LIMIT :limit
        """
    )
    result = await session.execute(
        sql,
        {
            "query_vector": vector,
            "model_name": model_name or settings.embedding_model_name,
            "exclude_summary_id": str(exclude_summary_id) if exclude_summary_id else None,
            "min_similarity": min_similarity,
            "limit": limit,
        },
    )
    return [Candidate(**dict(row._mapping)) for row in result]


def is_configured() -> bool:
    return True
