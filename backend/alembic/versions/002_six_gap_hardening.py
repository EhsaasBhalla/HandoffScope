"""Additive columns for AI Q&A draft provenance, primary transfer packs, and idempotent claim promotion.

Revision ID: 002_six_gap_hardening
Revises: 001_initial_schema
Create Date: 2026-11-11 12:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_six_gap_hardening"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "question_responses" in existing_tables:
        qr_cols = {c["name"] for c in inspector.get_columns("question_responses")}
        if "is_ai_generated" not in qr_cols:
            op.add_column(
                "question_responses",
                sa.Column("is_ai_generated", sa.Boolean(), server_default="false", nullable=False),
            )
        if "ai_provider" not in qr_cols:
            op.add_column("question_responses", sa.Column("ai_provider", sa.String(length=50), nullable=True))
        if "ai_model" not in qr_cols:
            op.add_column("question_responses", sa.Column("ai_model", sa.String(length=100), nullable=True))
        if "answer_status" not in qr_cols:
            op.add_column("question_responses", sa.Column("answer_status", sa.String(length=30), nullable=True))
        if "evidence_json" not in qr_cols:
            op.add_column("question_responses", sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        if "limitations" not in qr_cols:
            op.add_column("question_responses", sa.Column("limitations", sa.Text(), nullable=True))
        if "conflicts_json" not in qr_cols:
            op.add_column("question_responses", sa.Column("conflicts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        if "provenance_json" not in qr_cols:
            op.add_column("question_responses", sa.Column("provenance_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    if "transfer_packs" in existing_tables:
        tp_cols = {c["name"] for c in inspector.get_columns("transfer_packs")}
        if "is_primary" not in tp_cols:
            op.add_column(
                "transfer_packs",
                sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
            )

    if "claims" in existing_tables:
        claim_cols = {c["name"] for c in inspector.get_columns("claims")}
        if "origin_question_id" not in claim_cols:
            is_pg = bind.dialect.name == "postgresql"
            op.add_column(
                "claims",
                sa.Column(
                    "origin_question_id",
                    postgresql.UUID(as_uuid=True) if is_pg else sa.String(length=32),
                    nullable=True,
                ),
            )
            if is_pg:
                op.create_foreign_key(
                    "fk_claims_origin_question_id_questions",
                    "claims",
                    "questions",
                    ["origin_question_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
                op.create_unique_constraint("uq_claims_origin_question_id", "claims", ["origin_question_id"])
            op.create_index("uq_claims_origin_question_id", "claims", ["origin_question_id"], unique=True)
        if "provenance_json" not in claim_cols:
            op.add_column("claims", sa.Column("provenance_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    is_pg = bind.dialect.name == "postgresql"

    if "claims" in existing_tables:
        claim_cols = {c["name"] for c in inspector.get_columns("claims")}
        if "provenance_json" in claim_cols:
            op.drop_column("claims", "provenance_json")
        if "origin_question_id" in claim_cols:
            existing_indexes = {idx["name"] for idx in inspector.get_indexes("claims")}
            if "uq_claims_origin_question_id" in existing_indexes:
                op.drop_index("uq_claims_origin_question_id", table_name="claims")
            if is_pg:
                op.drop_constraint("uq_claims_origin_question_id", "claims", type_="unique")
                op.drop_constraint("fk_claims_origin_question_id_questions", "claims", type_="foreignkey")
            op.drop_column("claims", "origin_question_id")

    if "transfer_packs" in existing_tables:
        tp_cols = {c["name"] for c in inspector.get_columns("transfer_packs")}
        if "is_primary" in tp_cols:
            op.drop_column("transfer_packs", "is_primary")

    if "question_responses" in existing_tables:
        qr_cols = {c["name"] for c in inspector.get_columns("question_responses")}
        for col in (
            "provenance_json",
            "conflicts_json",
            "limitations",
            "evidence_json",
            "answer_status",
            "ai_model",
            "ai_provider",
            "is_ai_generated",
        ):
            if col in qr_cols:
                op.drop_column("question_responses", col)
