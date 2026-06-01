"""Local sentence-transformers embeddings and pgvector storage helpers."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Embedding


class EmbeddingService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._model: Any = None

    def load(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install the 'models' extra to use embeddings") from exc
        model_path = self.settings.embedding_model_path
        source = str(model_path) if model_path.exists() else self.settings.embedding_model_name
        self._model = SentenceTransformer(source)

    def embed(self, text: str) -> list[float]:
        if self._model is None:
            self.load()
        vector = self._model.encode(text, normalize_embeddings=True)
        values = [float(value) for value in vector]
        if len(values) != self.settings.embedding_dimensions:
            raise ValueError(f"Expected {self.settings.embedding_dimensions} dimensions, got {len(values)}")
        return values

    def embed_summary(self, summary_title: str, summary_text: str) -> list[float]:
        return self.embed(f"{summary_title}\n\n{summary_text}")


async def store_embedding(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: Any,
    text: str,
    vector: list[float],
    model_name: str | None = None,
) -> Embedding:
    """Create or update one embedding row per target/model."""
    settings = get_settings()
    resolved_model = model_name or settings.embedding_model_name
    text_digest = hash_text(text)
    existing = await get_existing_embedding(
        session, target_type=target_type, target_id=target_id, model_name=resolved_model
    )
    if existing is not None:
        existing.dimensions = len(vector)
        existing.embedding = vector
        existing.text_hash = text_digest
        await session.flush()
        return existing
    try:
        async with session.begin_nested():
            row = Embedding(
                target_type=target_type,
                target_id=target_id,
                model_name=resolved_model,
                dimensions=len(vector),
                embedding=vector,
                text_hash=text_digest,
            )
            session.add(row)
            await session.flush()
            return row
    except IntegrityError:
        # Another worker inserted the same target/model concurrently. Re-select and update.
        existing = await get_existing_embedding(
            session, target_type=target_type, target_id=target_id, model_name=resolved_model
        )
        if existing is None:
            raise
        existing.dimensions = len(vector)
        existing.embedding = vector
        existing.text_hash = text_digest
        await session.flush()
        return existing


async def get_existing_embedding(
    session: AsyncSession, *, target_type: str, target_id: Any, model_name: str | None = None
) -> Embedding | None:
    settings = get_settings()
    result = await session.execute(
        select(Embedding).where(
            Embedding.target_type == target_type,
            Embedding.target_id == target_id,
            Embedding.model_name == (model_name or settings.embedding_model_name),
        )
    )
    return result.scalar_one_or_none()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.embedding_model_name and settings.embedding_dimensions)
