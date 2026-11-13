"""Round 3 schema additions: RAG chunks/threads/messages, SourceType extensions, and claim delegation columns.

Revision ID: 003_round3_features
Revises: 002_six_gap_hardening
Create Date: 2026-11-12 13:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003_round3_features"
down_revision: Union[str, None] = "002_six_gap_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.String(length=32)
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if is_pg:
        for enum_name in ("source_type_enum", "sourcetype"):
            for val in ("GITLAB_REPO", "JIRA_PROJECT", "LINEAR_TEAM"):
                op.execute(
                    sa.text(
                        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_type WHERE typname = '{enum_name}') "
                        f"THEN ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{val}'; END IF; END $$;"
                    )
                )

    if "responsibility_assignments" in existing_tables:
        ra_cols = {c["name"] for c in inspector.get_columns("responsibility_assignments")}
        if "claim_id" not in ra_cols:
            op.add_column("responsibility_assignments", sa.Column("claim_id", uuid_type, nullable=True))
            if is_pg:
                op.create_foreign_key(
                    "fk_ra_claim_id_claims",
                    "responsibility_assignments",
                    "claims",
                    ["claim_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
        if "delegated_from_user_id" not in ra_cols:
            op.add_column("responsibility_assignments", sa.Column("delegated_from_user_id", uuid_type, nullable=True))
        if "delegation_note" not in ra_cols:
            op.add_column("responsibility_assignments", sa.Column("delegation_note", sa.Text(), nullable=True))
        if "revoked_at" not in ra_cols:
            op.add_column("responsibility_assignments", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))

    if "knowledge_chunks" not in existing_tables:
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("workspace_id", uuid_type, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", uuid_type, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("case_id", uuid_type, sa.ForeignKey("handover_cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version_id", uuid_type, sa.ForeignKey("handover_versions.id", ondelete="CASCADE"), nullable=True),
            sa.Column("context_mode", sa.String(30), nullable=False),
            sa.Column("source_kind", sa.String(40), nullable=False),
            sa.Column("source_ref_id", sa.String(100), nullable=False),
            sa.Column("source_revision", sa.String(128), nullable=True),
            sa.Column("sensitivity", sa.String(30), nullable=False, server_default="GENERAL"),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("content_text", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("locator_json", json_type, nullable=True),
            sa.Column("metadata_json", json_type, nullable=True),
            sa.Column("embedding_json", json_type, nullable=True),
            sa.Column("embedding_model", sa.String(100), nullable=True),
            sa.Column("embedding_dimension", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "rag_threads" not in existing_tables:
        op.create_table(
            "rag_threads",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("case_id", uuid_type, sa.ForeignKey("handover_cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("context_mode", sa.String(30), nullable=False),
            sa.Column("pinned_version_id", uuid_type, sa.ForeignKey("handover_versions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("pinned_version_number", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "rag_messages" not in existing_tables:
        op.create_table(
            "rag_messages",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("thread_id", uuid_type, sa.ForeignKey("rag_threads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("content_text", sa.Text(), nullable=False),
            sa.Column("grounding_status", sa.String(40), nullable=True),
            sa.Column("citations_json", json_type, nullable=True),
            sa.Column("limitations", sa.Text(), nullable=True),
            sa.Column("retrieval_mode", sa.String(40), nullable=True),
            sa.Column("provider_name", sa.String(50), nullable=True),
            sa.Column("model_used", sa.String(100), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    # Reversible drop of newly introduced additive Round 3 tables/columns
    op.drop_table("rag_messages")
    op.drop_table("rag_threads")
    op.drop_table("knowledge_chunks")
    with op.batch_alter_table("responsibility_assignments") as batch_op:
        batch_op.drop_column("revoked_at")
        batch_op.drop_column("delegation_note")
        batch_op.drop_column("delegated_from_user_id")
        batch_op.drop_column("claim_id")
