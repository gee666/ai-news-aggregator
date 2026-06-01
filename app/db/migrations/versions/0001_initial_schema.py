"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-29
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_many(sql: str) -> None:
    for statement in sql.split(";"):
        statement = statement.strip()
        if statement:
            op.execute(statement)


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _execute_many(
        """
        CREATE TABLE sources (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            source_type text NOT NULL,
            name text NOT NULL,
            url text,
            identifier text,
            config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            active boolean NOT NULL DEFAULT true,
            dt_created timestamptz NOT NULL DEFAULT now(),
            dt_updated timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX uq_sources_type_identifier ON sources (source_type, identifier) WHERE identifier IS NOT NULL;

        CREATE TABLE raw_items (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            source_id uuid REFERENCES sources(id),
            external_id text,
            title text,
            raw_text text,
            raw_html text,
            original_url text,
            published_at timestamptz,
            collected_at timestamptz NOT NULL DEFAULT now(),
            content_hash text,
            metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            status text NOT NULL DEFAULT 'new',
            rejection_reason text,
            duplicate_of_raw_item_id uuid REFERENCES raw_items(id),
            dt_created timestamptz NOT NULL DEFAULT now(),
            dt_updated timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX uq_raw_items_source_external ON raw_items (source_id, external_id) WHERE source_id IS NOT NULL AND external_id IS NOT NULL;
        CREATE INDEX ix_raw_items_content_hash ON raw_items (content_hash);
        CREATE INDEX ix_raw_items_status ON raw_items (status);
        CREATE INDEX ix_raw_items_published_at ON raw_items (published_at);

        CREATE TABLE raw_item_links (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            raw_item_id uuid NOT NULL REFERENCES raw_items(id),
            url text NOT NULL,
            normalized_url text NOT NULL,
            domain text,
            link_text text,
            position int,
            is_primary boolean DEFAULT false,
            status text DEFAULT 'new',
            dt_created timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_raw_item_links_normalized_url ON raw_item_links (normalized_url);
        CREATE INDEX ix_raw_item_links_domain ON raw_item_links (domain);
        CREATE INDEX ix_raw_item_links_raw_item_id ON raw_item_links (raw_item_id);

        CREATE TABLE documents (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            raw_item_id uuid REFERENCES raw_items(id),
            source_link_id uuid REFERENCES raw_item_links(id),
            url text NOT NULL,
            canonical_url text,
            root_source_url text,
            domain text,
            title text,
            cleaned_text text,
            html text,
            language text,
            published_at timestamptz,
            author text,
            content_hash text,
            extraction_method text,
            trust_level text,
            source_role text,
            is_root_source boolean DEFAULT false,
            rejection_reason text,
            metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            dt_created timestamptz NOT NULL DEFAULT now(),
            dt_updated timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_documents_canonical_url ON documents (canonical_url);
        CREATE INDEX ix_documents_root_source_url ON documents (root_source_url);
        CREATE INDEX ix_documents_content_hash ON documents (content_hash);
        CREATE INDEX ix_documents_domain ON documents (domain);
        CREATE INDEX ix_documents_trust_level ON documents (trust_level);
        CREATE INDEX ix_documents_source_role ON documents (source_role);

        CREATE TABLE trusted_sources (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            domain text NOT NULL UNIQUE,
            name text,
            trust_level text,
            source_type text,
            notes text,
            active boolean DEFAULT true,
            dt_created timestamptz NOT NULL DEFAULT now(),
            dt_updated timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE trusted_social_accounts (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            platform text NOT NULL,
            handle text NOT NULL,
            entity_name text,
            trust_level text,
            notes text,
            active boolean DEFAULT true,
            dt_created timestamptz NOT NULL DEFAULT now(),
            dt_updated timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE summaries (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            target_type text NOT NULL,
            target_id uuid NOT NULL,
            summary_title text NOT NULL,
            summary_text text NOT NULL,
            summary_template_version text,
            model_name text,
            prompt_version text,
            source_links_json jsonb NOT NULL DEFAULT '[]'::jsonb,
            metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            dt_created timestamptz NOT NULL DEFAULT now(),
            dt_updated timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_summaries_target ON summaries (target_type, target_id);
        CREATE INDEX ix_summaries_dt_created ON summaries (dt_created);

        CREATE TABLE summary_links (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            summary_id uuid NOT NULL REFERENCES summaries(id),
            url text NOT NULL,
            normalized_url text,
            canonical_url text,
            domain text,
            link_type text,
            trust_level text,
            dt_created timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE embeddings (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            target_type text NOT NULL,
            target_id uuid NOT NULL,
            model_name text NOT NULL,
            dimensions int NOT NULL,
            embedding vector(384) NOT NULL,
            text_hash text,
            dt_created timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX embeddings_vector_cosine_idx ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
        CREATE UNIQUE INDEX uq_embeddings_target_model ON embeddings (target_type, target_id, model_name);
        CREATE INDEX ix_embeddings_target ON embeddings (target_type, target_id);
        CREATE INDEX ix_embeddings_model_name ON embeddings (model_name);

        CREATE TABLE story_clusters (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            title text NOT NULL,
            combined_summary_id uuid REFERENCES summaries(id),
            status text NOT NULL DEFAULT 'active',
            first_seen_at timestamptz,
            last_seen_at timestamptz,
            metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            dt_created timestamptz NOT NULL DEFAULT now(),
            dt_updated timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE story_cluster_items (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            cluster_id uuid NOT NULL REFERENCES story_clusters(id),
            summary_id uuid NOT NULL REFERENCES summaries(id),
            document_id uuid REFERENCES documents(id),
            raw_item_id uuid REFERENCES raw_items(id),
            similarity_score float,
            match_confidence float,
            match_reason text,
            is_primary boolean DEFAULT false,
            dt_created timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE related_stories (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            cluster_id_a uuid NOT NULL REFERENCES story_clusters(id),
            cluster_id_b uuid NOT NULL REFERENCES story_clusters(id),
            relation_type text,
            confidence float,
            reason text,
            dt_created timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE tags (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            name text NOT NULL,
            slug text NOT NULL UNIQUE,
            tag_type text,
            dt_created timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE cluster_tags (
            cluster_id uuid NOT NULL REFERENCES story_clusters(id),
            tag_id uuid NOT NULL REFERENCES tags(id),
            confidence float,
            source text,
            PRIMARY KEY (cluster_id, tag_id)
        );
        """
    )


def downgrade() -> None:
    _execute_many(
        """
        DROP TABLE IF EXISTS cluster_tags;
        DROP TABLE IF EXISTS tags;
        DROP TABLE IF EXISTS related_stories;
        DROP TABLE IF EXISTS story_cluster_items;
        DROP TABLE IF EXISTS story_clusters;
        DROP TABLE IF EXISTS embeddings;
        DROP TABLE IF EXISTS summary_links;
        DROP TABLE IF EXISTS summaries;
        DROP TABLE IF EXISTS trusted_social_accounts;
        DROP TABLE IF EXISTS trusted_sources;
        DROP TABLE IF EXISTS documents;
        DROP TABLE IF EXISTS raw_item_links;
        DROP TABLE IF EXISTS raw_items;
        DROP TABLE IF EXISTS sources;
        """
    )
