"""Idempotent additive database schema guard for startup and test fixtures."""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text


def register_all_models() -> None:
    """Import all ORM models so SQLAlchemy metadata is complete."""
    import app.modules.workspaces.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.audit.models  # noqa: F401
    import app.modules.handover_cases.models  # noqa: F401
    import app.modules.sources.models  # noqa: F401
    import app.modules.ingestion.models  # noqa: F401
    import app.modules.jobs.models  # noqa: F401
    import app.modules.documents.models  # noqa: F401
    import app.modules.transfer_packs.models  # noqa: F401
    import app.modules.questions.models  # noqa: F401
    import app.modules.identity.models  # noqa: F401
    import app.modules.evidence.models  # noqa: F401
    import app.modules.reviews.models  # noqa: F401
    import app.modules.sharing.models  # noqa: F401
    import app.modules.recipients.models  # noqa: F401
    import app.modules.rag.models  # noqa: F401


def ensure_additive_schema(bind_engine: Engine) -> None:
    """Create missing tables and apply safe additive columns/indexes."""
    from app.db.base import Base

    register_all_models()
    Base.metadata.create_all(bind=bind_engine)

    is_pg = bind_engine.dialect.name == "postgresql"
    json_sql = "JSONB" if is_pg else "JSON"
    uuid_sql = "UUID" if is_pg else "CHAR(32)"

    # Safely extend PostgreSQL enum types when existing DB predates Round 3 enum values
    if is_pg:
        for enum_name, enum_val in (
            ("source_type_enum", "GITLAB_REPO"),
            ("source_type_enum", "JIRA_PROJECT"),
            ("source_type_enum", "LINEAR_TEAM"),
            ("sourcetype", "GITLAB_REPO"),
            ("sourcetype", "JIRA_PROJECT"),
            ("sourcetype", "LINEAR_TEAM"),
        ):
            try:
                with bind_engine.begin() as conn:
                    conn.execute(
                        text(
                            "DO $$ BEGIN "
                            f"IF EXISTS (SELECT 1 FROM pg_type WHERE typname = '{enum_name}') THEN "
                            f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{enum_val}'; "
                            "END IF; "
                            "END $$;"
                        )
                    )
            except Exception:
                pass

    inspector = inspect(bind_engine)
    existing_tables = set(inspector.get_table_names())

    def _ensure_column(table: str, col_name: str, col_ddl: str) -> None:
        if table not in existing_tables:
            return
        cols = {c["name"] for c in inspector.get_columns(table)}
        if col_name not in cols:
            with bind_engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_ddl}"))

    _ensure_column("source_records", "author_mapped_user_id", uuid_sql)
    _ensure_column("claims", "original_body_text", "TEXT")
    _ensure_column("claims", "review_notes", "TEXT")
    _ensure_column("claims", "origin_question_id", uuid_sql)
    _ensure_column("claims", "provenance_json", json_sql)
    _ensure_column("transfer_packs", "is_primary", "BOOLEAN DEFAULT FALSE NOT NULL")
    _ensure_column("question_responses", "is_ai_generated", "BOOLEAN DEFAULT FALSE NOT NULL")
    _ensure_column("question_responses", "ai_provider", "VARCHAR(50)")
    _ensure_column("question_responses", "ai_model", "VARCHAR(100)")
    _ensure_column("question_responses", "answer_status", "VARCHAR(30)")
    _ensure_column("question_responses", "evidence_json", json_sql)
    _ensure_column("question_responses", "limitations", "TEXT")
    _ensure_column("question_responses", "conflicts_json", json_sql)
    _ensure_column("question_responses", "provenance_json", json_sql)
    _ensure_column("responsibility_assignments", "claim_id", uuid_sql)
    _ensure_column("responsibility_assignments", "delegated_from_user_id", uuid_sql)
    _ensure_column("responsibility_assignments", "delegation_note", "TEXT")
    _ensure_column("responsibility_assignments", "revoked_at", "TIMESTAMP WITH TIME ZONE" if is_pg else "DATETIME")

    if "claims" in existing_tables:
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("claims")}
        if (
            "uq_claims_origin_question_id" not in existing_indexes
            and "ix_claims_origin_question_id" not in existing_indexes
        ):
            try:
                with bind_engine.begin() as conn:
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX uq_claims_origin_question_id "
                            "ON claims (origin_question_id)"
                        )
                    )
            except Exception:
                pass
