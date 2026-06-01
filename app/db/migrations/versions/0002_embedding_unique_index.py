"""add unique embedding target/model index

Revision ID: 0002_embedding_unique_index
Revises: 0001_initial_schema
Create Date: 2026-05-29
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002_embedding_unique_index"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM embeddings a
        USING embeddings b
        WHERE a.ctid < b.ctid
          AND a.target_type = b.target_type
          AND a.target_id = b.target_id
          AND a.model_name = b.model_name
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_embeddings_target_model "
        "ON embeddings (target_type, target_id, model_name)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_embeddings_target_model")
