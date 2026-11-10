"""Initial schema for Phases 1 through 4.

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-11-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Users ──────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=150), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
        sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # ── 2. Workspaces ─────────────────────────────────────────
    op.create_table(
        'workspaces',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_workspaces')),
        sa.UniqueConstraint('slug', name=op.f('uq_workspaces_slug'))
    )
    op.create_index(op.f('ix_workspaces_slug'), 'workspaces', ['slug'], unique=True)

    # ── 3. Workspace Memberships ──────────────────────────────
    op.create_table(
        'workspace_memberships',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_workspace_memberships_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workspace_memberships_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_workspace_memberships')),
        sa.UniqueConstraint('user_id', 'workspace_id', name='uq_workspace_membership')
    )

    # ── 4. Projects ───────────────────────────────────────────
    op.create_table(
        'projects',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('repo_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_projects_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_projects')),
        sa.UniqueConstraint('workspace_id', 'slug', name='uq_project_workspace_slug')
    )
    op.create_index(op.f('ix_projects_slug'), 'projects', ['slug'], unique=False)

    # ── 5. Project Memberships ────────────────────────────────
    op.create_table(
        'project_memberships',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_memberships_project_id_projects'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_project_memberships_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_project_memberships')),
        sa.UniqueConstraint('user_id', 'project_id', name='uq_project_membership')
    )

    # ── 6. Audit Events ───────────────────────────────────────
    op.create_table(
        'audit_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_events_actor_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index(op.f('ix_audit_events_action'), 'audit_events', ['action'], unique=False)
    op.create_index(op.f('ix_audit_events_created_at'), 'audit_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_events_entity_type'), 'audit_events', ['entity_type'], unique=False)

    # ── 7. Handover Cases ─────────────────────────────────────
    op.create_table(
        'handover_cases',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('case_number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('transition_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='DRAFT', nullable=False),
        sa.Column('sync_status', sa.String(length=50), server_default='UNKNOWN_FRESHNESS', nullable=False),
        sa.Column('is_blocked', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('blocked_reason', sa.Text(), nullable=True),
        sa.Column('scope_start', sa.Date(), nullable=True),
        sa.Column('scope_end', sa.Date(), nullable=True),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_handover_cases_created_by_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_handover_cases_project_id_projects'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_handover_cases')),
        sa.UniqueConstraint('project_id', 'case_number', name='uq_case_number_per_project')
    )
    op.create_index(op.f('ix_handover_cases_status'), 'handover_cases', ['status'], unique=False)

    # ── 8. Case Participants ──────────────────────────────────
    op.create_table(
        'case_participants',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['handover_cases.id'], name=op.f('fk_case_participants_case_id_handover_cases'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_case_participants_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_case_participants')),
        sa.UniqueConstraint('case_id', 'user_id', 'role', name='uq_case_participant_role')
    )

    # ── 9. Case Sources ───────────────────────────────────────
    op.create_table(
        'case_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('connected_source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('added_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['added_by_id'], ['users.id'], name=op.f('fk_case_sources_added_by_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['case_id'], ['handover_cases.id'], name=op.f('fk_case_sources_case_id_handover_cases'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_case_sources')),
        sa.UniqueConstraint('case_id', 'connected_source_id', name='uq_case_source')
    )

    # ── 10. Connected Sources ─────────────────────────────────
    op.create_table(
        'connected_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=300), nullable=False),
        sa.Column('external_id', sa.String(length=500), nullable=True),
        sa.Column('connection_status', sa.String(length=50), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('connected_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['connected_by_id'], ['users.id'], name=op.f('fk_connected_sources_connected_by_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_connected_sources_project_id_projects'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_connected_sources')),
        sa.UniqueConstraint('project_id', 'source_type', 'external_id', name='uq_source_identity')
    )

    # ── 11. Sync Runs ─────────────────────────────────────────
    op.create_table(
        'sync_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('records_fetched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('records_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('records_updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['source_id'], ['connected_sources.id'], name=op.f('fk_sync_runs_source_id_connected_sources'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sync_runs'))
    )

    # ── 12. GitHub Installations ──────────────────────────────
    op.create_table(
        'github_installations',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('installation_id', sa.Integer(), nullable=False),
        sa.Column('account_login', sa.String(length=200), nullable=False),
        sa.Column('account_type', sa.String(length=50), server_default='Organization', nullable=False),
        sa.Column('access_token', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('installed_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['installed_by_id'], ['users.id'], name=op.f('fk_github_installations_installed_by_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_github_installations_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_github_installations')),
        sa.UniqueConstraint('installation_id', name=op.f('uq_github_installations_installation_id'))
    )

    # ── 13. Source Records ────────────────────────────────────
    op.create_table(
        'source_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('connected_source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('record_type', sa.String(length=50), nullable=False),
        sa.Column('external_id', sa.String(length=500), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('author_external_id', sa.String(length=200), nullable=True),
        sa.Column('author_name', sa.String(length=200), nullable=True),
        sa.Column('state', sa.String(length=50), nullable=True),
        sa.Column('url', sa.String(length=1000), nullable=True),
        sa.Column('sensitivity', sa.String(length=50), nullable=False),
        sa.Column('processing_status', sa.String(length=50), nullable=False),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('external_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('external_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['connected_source_id'], ['connected_sources.id'], name=op.f('fk_source_records_connected_source_id_connected_sources'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_records')),
        sa.UniqueConstraint('connected_source_id', 'record_type', 'external_id', name='uq_source_record_identity')
    )

    # ── 14. Source Events ─────────────────────────────────────
    op.create_table(
        'source_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('record_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('external_id', sa.String(length=500), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('author_external_id', sa.String(length=200), nullable=True),
        sa.Column('author_name', sa.String(length=200), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['record_id'], ['source_records.id'], name=op.f('fk_source_events_record_id_source_records'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_events')),
        sa.UniqueConstraint('record_id', 'event_type', 'external_id', name='uq_source_event_identity')
    )

    # ── 15. Jobs ──────────────────────────────────────────────
    op.create_table(
        'jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('job_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('idempotency_key', sa.String(length=500), nullable=True),
        sa.Column('progress_current', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('progress_total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('progress_message', sa.String(length=500), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('entity_type', sa.String(length=50), nullable=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('locked_by', sa.String(length=200), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_jobs_created_by_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs')),
        sa.UniqueConstraint('idempotency_key', name=op.f('uq_jobs_idempotency_key'))
    )
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)

    # ── 16. Documents ─────────────────────────────────────────
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('filename', sa.String(length=500), nullable=False),
        sa.Column('original_filename', sa.String(length=500), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('storage_path', sa.String(length=1000), nullable=False),
        sa.Column('file_hash', sa.String(length=128), nullable=False),
        sa.Column('processing_status', sa.String(length=50), nullable=False),
        sa.Column('sensitivity', sa.String(length=50), nullable=False),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('section_count', sa.Integer(), nullable=True),
        sa.Column('extraction_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('uploaded_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_documents_project_id_projects'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], name=op.f('fk_documents_uploaded_by_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_documents'))
    )
    op.create_index(op.f('ix_documents_file_hash'), 'documents', ['file_hash'], unique=False)


def downgrade() -> None:
    op.drop_table('documents')
    op.drop_table('jobs')
    op.drop_table('source_events')
    op.drop_table('source_records')
    op.drop_table('github_installations')
    op.drop_table('sync_runs')
    op.drop_table('connected_sources')
    op.drop_table('case_sources')
    op.drop_table('case_participants')
    op.drop_table('handover_cases')
    op.drop_table('audit_events')
    op.drop_table('project_memberships')
    op.drop_table('projects')
    op.drop_table('workspace_memberships')
    op.drop_table('workspaces')
    op.drop_table('users')
