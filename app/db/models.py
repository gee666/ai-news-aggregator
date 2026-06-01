import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, UserDefinedType


class PGVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dimensions})"


class Vector(TypeDecorator[list[float]]):
    """pgvector-compatible type with text fallback for non-PostgreSQL tooling."""

    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int = 384, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGVector(self.dimensions))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return "[" + ",".join(str(float(v)) for v in value) + "]"
        return ",".join(str(float(v)) for v in value)

    def process_result_value(self, value: Any, dialect: Any) -> list[float] | None:
        if value is None or isinstance(value, list):
            return value
        text = str(value).strip("[]")
        return [float(part) for part in text.split(",") if part]


class Base(DeclarativeBase):
    pass


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def updated_at():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


def json_dict():
    return mapped_column(JSONB, nullable=False, server_default="{}")


def json_list():
    return mapped_column(JSONB, nullable=False, server_default="[]")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        Index(
            "uq_sources_type_identifier",
            "source_type",
            "identifier",
            unique=True,
            postgresql_where=text("identifier IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    identifier: Mapped[str | None] = mapped_column(Text)
    config_json: Mapped[dict[str, Any]] = json_dict()
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    dt_created: Mapped[datetime] = created_at()
    dt_updated: Mapped[datetime] = updated_at()


class RawItem(Base):
    __tablename__ = "raw_items"
    __table_args__ = (
        Index(
            "uq_raw_items_source_external",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=text("source_id IS NOT NULL AND external_id IS NOT NULL"),
        ),
        Index("ix_raw_items_content_hash", "content_hash"),
        Index("ix_raw_items_status", "status"),
        Index("ix_raw_items_published_at", "published_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    raw_html: Mapped[str | None] = mapped_column(Text)
    original_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    content_hash: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = json_dict()
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    duplicate_of_raw_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_items.id"))
    dt_created: Mapped[datetime] = created_at()
    dt_updated: Mapped[datetime] = updated_at()


class RawItemLink(Base):
    __tablename__ = "raw_item_links"
    __table_args__ = (
        Index("ix_raw_item_links_normalized_url", "normalized_url"),
        Index("ix_raw_item_links_domain", "domain"),
        Index("ix_raw_item_links_raw_item_id", "raw_item_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    raw_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(Text)
    link_text: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default="false")
    status: Mapped[str] = mapped_column(Text, server_default="new")
    dt_created: Mapped[datetime] = created_at()


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_canonical_url", "canonical_url"),
        Index("ix_documents_root_source_url", "root_source_url"),
        Index("ix_documents_content_hash", "content_hash"),
        Index("ix_documents_domain", "domain"),
        Index("ix_documents_trust_level", "trust_level"),
        Index("ix_documents_source_role", "source_role"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    raw_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_items.id"))
    source_link_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_item_links.id"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    root_source_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    cleaned_text: Mapped[str | None] = mapped_column(Text)
    html: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    author: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str | None] = mapped_column(Text)
    trust_level: Mapped[str | None] = mapped_column(Text)
    source_role: Mapped[str | None] = mapped_column(Text)
    is_root_source: Mapped[bool] = mapped_column(Boolean, server_default="false")
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = json_dict()
    dt_created: Mapped[datetime] = created_at()
    dt_updated: Mapped[datetime] = updated_at()


class TrustedSource(Base):
    __tablename__ = "trusted_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    domain: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    trust_level: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    dt_created: Mapped[datetime] = created_at()
    dt_updated: Mapped[datetime] = updated_at()


class TrustedSocialAccount(Base):
    __tablename__ = "trusted_social_accounts"

    id: Mapped[uuid.UUID] = uuid_pk()
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    entity_name: Mapped[str | None] = mapped_column(Text)
    trust_level: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    dt_created: Mapped[datetime] = created_at()
    dt_updated: Mapped[datetime] = updated_at()


class Summary(Base):
    __tablename__ = "summaries"
    __table_args__ = (
        Index("ix_summaries_target", "target_type", "target_id"),
        Index("ix_summaries_dt_created", "dt_created"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    summary_title: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary_template_version: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    source_links_json: Mapped[list[dict[str, Any]]] = json_list()
    metadata_json: Mapped[dict[str, Any]] = json_dict()
    dt_created: Mapped[datetime] = created_at()
    dt_updated: Mapped[datetime] = updated_at()


class SummaryLink(Base):
    __tablename__ = "summary_links"

    id: Mapped[uuid.UUID] = uuid_pk()
    summary_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("summaries.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    link_type: Mapped[str | None] = mapped_column(Text)
    trust_level: Mapped[str | None] = mapped_column(Text)
    dt_created: Mapped[datetime] = created_at()


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        Index(
            "embeddings_vector_cosine_idx",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"lists": 100},
        ),
        Index("uq_embeddings_target_model", "target_type", "target_id", "model_name", unique=True),
        Index("ix_embeddings_target", "target_type", "target_id"),
        Index("ix_embeddings_model_name", "model_name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    text_hash: Mapped[str | None] = mapped_column(Text)
    dt_created: Mapped[datetime] = created_at()


class StoryCluster(Base):
    __tablename__ = "story_clusters"

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    combined_summary_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("summaries.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = json_dict()
    dt_created: Mapped[datetime] = created_at()
    dt_updated: Mapped[datetime] = updated_at()


class StoryClusterItem(Base):
    __tablename__ = "story_cluster_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    cluster_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("story_clusters.id"), nullable=False)
    summary_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("summaries.id"), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    raw_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_items.id"))
    similarity_score: Mapped[float | None] = mapped_column(Float)
    match_confidence: Mapped[float | None] = mapped_column(Float)
    match_reason: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default="false")
    dt_created: Mapped[datetime] = created_at()


class RelatedStory(Base):
    __tablename__ = "related_stories"

    id: Mapped[uuid.UUID] = uuid_pk()
    cluster_id_a: Mapped[uuid.UUID] = mapped_column(ForeignKey("story_clusters.id"), nullable=False)
    cluster_id_b: Mapped[uuid.UUID] = mapped_column(ForeignKey("story_clusters.id"), nullable=False)
    relation_type: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    dt_created: Mapped[datetime] = created_at()


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    tag_type: Mapped[str | None] = mapped_column(Text)
    dt_created: Mapped[datetime] = created_at()


class ClusterTag(Base):
    __tablename__ = "cluster_tags"

    cluster_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("story_clusters.id"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(Text)
