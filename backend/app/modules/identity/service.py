"""Identity mapping service — auto-suggesting, listing, and reviewing contributor identities."""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.enums import IdentityConfidence
from app.modules.audit.service import create_audit_event
from app.modules.identity.models import IdentityMapping
from app.modules.identity.schemas import (
    IdentityCoverageOut,
    IdentityMappingCreate,
    IdentityMappingOut,
    IdentityMappingUpdate,
)
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project, ProjectMembership
from app.modules.sources.models import ConnectedSource
from app.modules.workspaces.models import User, WorkspaceMembership

logger = logging.getLogger("handoffscope.identity")


def _get_project_source_ids(db: Session, project_id: uuid.UUID) -> list[uuid.UUID]:
    """Helper to get all connected source IDs for a project."""
    rows = db.query(ConnectedSource.id).filter(ConnectedSource.project_id == project_id).all()
    return [r[0] for r in rows]


def auto_suggest_mappings(db: Session, project_id: uuid.UUID) -> list[IdentityMappingOut]:
    """Scan imported source records, detect distinct authors, and suggest user matches."""
    source_ids = _get_project_source_ids(db, project_id)
    if not source_ids:
        return list_mappings(db, project_id)

    # 1. Distinct external authors with source_type, optional email in metadata, and contribution counts
    raw_records = (
        db.query(SourceRecord)
        .filter(
            SourceRecord.connected_source_id.in_(source_ids),
            SourceRecord.author_external_id.isnot(None),
            SourceRecord.author_external_id != "",
        )
        .all()
    )
    if not raw_records:
        return list_mappings(db, project_id)

    _BOT_MARKERS = ("[bot]", "dependabot", "renovate", "github-actions", "gitlab-bot")
    _PROVIDER_MAP = {
        "GITHUB_REPO": "github",
        "GITLAB_REPO": "gitlab",
        "JIRA_PROJECT": "jira",
        "LINEAR_TEAM": "linear",
        "SYNTHETIC_FIXTURE": "github",
    }
    grouped_authors: dict[str, dict] = {}
    for rec in raw_records:
        ext_u = (rec.author_external_id or "").strip()
        if not ext_u or any(b in ext_u.lower() for b in _BOT_MARKERS):
            continue
        info = grouped_authors.setdefault(
            ext_u,
            {
                "author_name": rec.author_name or "",
                "provider": _PROVIDER_MAP.get(rec.source_type, "github"),
                "author_email": None,
            },
        )
        if rec.author_name and not info["author_name"]:
            info["author_name"] = rec.author_name
        meta_email = (rec.metadata_json or {}).get("author_email") if isinstance(rec.metadata_json, dict) else None
        if isinstance(meta_email, str) and "@" in meta_email and not info["author_email"]:
            info["author_email"] = meta_email.strip().lower()

    if not grouped_authors:
        return list_mappings(db, project_id)

    # 2. Get project/workspace users for matching
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    users = (
        db.query(User)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .filter(WorkspaceMembership.workspace_id == project.workspace_id)
        .all()
    )

    existing_mappings = {
        m.external_username: m
        for m in db.query(IdentityMapping).filter(IdentityMapping.project_id == project_id).all()
    }

    # 3. Match each author strictly as SUGGESTED (never auto-promote fuzzy/email matches to VERIFIED)
    for ext_username, info in grouped_authors.items():
        norm_ext = ext_username.lower().strip()
        norm_name = (info["author_name"] or "").lower().strip()
        ext_email = info["author_email"]

        candidate_user: User | None = None

        # Check 1: Verified/exact email match from connector metadata (SUGGESTED until Lead confirms)
        if ext_email:
            for u in users:
                if u.email.lower() == ext_email:
                    candidate_user = u
                    break

        # Check 2: Exact match on email prefix
        if not candidate_user:
            for u in users:
                email_prefix = u.email.split("@")[0].lower()
                if email_prefix == norm_ext or email_prefix.replace(".", "") == norm_ext.replace("-", "").replace("_", ""):
                    candidate_user = u
                    break

        # Check 3: Exact display name
        if not candidate_user and norm_name:
            for u in users:
                if u.display_name.lower() == norm_name:
                    candidate_user = u
                    break

        # Check 4: Substring / contains match (suggestion only)
        if not candidate_user:
            for u in users:
                u_norm = u.display_name.lower().replace(" ", "")
                if norm_ext in u.email.lower() or (len(norm_ext) >= 4 and norm_ext in u_norm):
                    candidate_user = u
                    break

        if ext_username in existing_mappings:
            mapping = existing_mappings[ext_username]
            if mapping.confidence != IdentityConfidence.VERIFIED:
                if candidate_user:
                    mapping.mapped_user_id = candidate_user.id
                    mapping.confidence = IdentityConfidence.SUGGESTED
        else:
            new_mapping = IdentityMapping(
                id=uuid.uuid4(),
                project_id=project_id,
                external_provider=info["provider"],
                external_username=ext_username,
                external_id=ext_username,
                mapped_user_id=candidate_user.id if candidate_user else None,
                confidence=IdentityConfidence.SUGGESTED if candidate_user else IdentityConfidence.UNMATCHED,
            )
            db.add(new_mapping)
            existing_mappings[ext_username] = new_mapping

    db.commit()

    # Automatically propagate verified mappings to source records
    propagate_verified_mappings(db, project_id)

    return list_mappings(db, project_id)


def propagate_verified_mappings(db: Session, project_id: uuid.UUID) -> None:
    """Propagate all VERIFIED identity mappings to source_records.author_mapped_user_id."""
    source_ids = _get_project_source_ids(db, project_id)
    if not source_ids:
        return

    verified_mappings = (
        db.query(IdentityMapping)
        .filter(
            IdentityMapping.project_id == project_id,
            IdentityMapping.confidence == IdentityConfidence.VERIFIED,
            IdentityMapping.mapped_user_id.isnot(None),
        )
        .all()
    )

    for vm in verified_mappings:
        db.query(SourceRecord).filter(
            SourceRecord.connected_source_id.in_(source_ids),
            SourceRecord.author_external_id == vm.external_username,
        ).update(
            {SourceRecord.author_mapped_user_id: vm.mapped_user_id},
            synchronize_session=False,
        )

    db.commit()


def list_mappings(
    db: Session,
    project_id: uuid.UUID,
    confidence: IdentityConfidence | None = None,
) -> list[IdentityMappingOut]:
    """List all identity mappings for a project with contribution counts and user details."""
    source_ids = _get_project_source_ids(db, project_id)

    # Contribution counts per external author
    contributions_map: dict[str, int] = {}
    if source_ids:
        counts = (
            db.query(
                SourceRecord.author_external_id,
                func.count(SourceRecord.id),
            )
            .filter(
                SourceRecord.connected_source_id.in_(source_ids),
                SourceRecord.author_external_id.isnot(None),
            )
            .group_by(SourceRecord.author_external_id)
            .all()
        )
        for author_id, cnt in counts:
            contributions_map[author_id] = cnt

    query = db.query(IdentityMapping).filter(IdentityMapping.project_id == project_id)
    if confidence:
        query = query.filter(IdentityMapping.confidence == confidence)

    mappings = query.order_by(IdentityMapping.created_at.desc()).all()

    # Preload user lookups
    user_ids = set()
    for m in mappings:
        if m.mapped_user_id:
            user_ids.add(m.mapped_user_id)
        if m.verified_by:
            user_ids.add(m.verified_by)

    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        users_map = {u.id: u for u in users}

    result = []
    for m in mappings:
        mapped_user = users_map.get(m.mapped_user_id)
        verifier = users_map.get(m.verified_by)
        result.append(
            IdentityMappingOut(
                id=m.id,
                project_id=m.project_id,
                external_provider=m.external_provider,
                external_username=m.external_username,
                external_id=m.external_id,
                mapped_user_id=m.mapped_user_id,
                mapped_user_name=mapped_user.display_name if mapped_user else None,
                mapped_user_email=mapped_user.email if mapped_user else None,
                confidence=m.confidence,
                verified_by=m.verified_by,
                verified_by_name=verifier.display_name if verifier else None,
                contributions_count=contributions_map.get(m.external_username, 0),
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
        )

    return result


def create_mapping(
    db: Session,
    project_id: uuid.UUID,
    data: IdentityMappingCreate,
    actor_id: uuid.UUID | None = None,
) -> IdentityMappingOut:
    """Manually create or overwrite an identity mapping."""
    ext_id = data.external_id or data.external_username
    existing = (
        db.query(IdentityMapping)
        .filter(
            IdentityMapping.project_id == project_id,
            IdentityMapping.external_provider == data.external_provider,
            IdentityMapping.external_username == data.external_username,
        )
        .first()
    )

    if existing:
        existing.mapped_user_id = data.mapped_user_id
        existing.confidence = data.confidence
        if data.confidence == IdentityConfidence.VERIFIED:
            existing.verified_by = actor_id
        mapping = existing
    else:
        mapping = IdentityMapping(
            id=uuid.uuid4(),
            project_id=project_id,
            external_provider=data.external_provider,
            external_username=data.external_username,
            external_id=ext_id,
            mapped_user_id=data.mapped_user_id,
            confidence=data.confidence,
            verified_by=actor_id if data.confidence == IdentityConfidence.VERIFIED else None,
        )
        db.add(mapping)

    db.commit()
    db.refresh(mapping)

    if mapping.confidence == IdentityConfidence.VERIFIED and mapping.mapped_user_id:
        propagate_verified_mappings(db, project_id)

    # Return mapped item
    items = list_mappings(db, project_id)
    return next((i for i in items if i.id == mapping.id), None)  # type: ignore


def update_mapping(
    db: Session,
    mapping_id: uuid.UUID,
    actor_id: uuid.UUID,
    update_data: IdentityMappingUpdate,
) -> IdentityMappingOut:
    """Update mapping status: confirm (verify), reject, or remap."""
    mapping = db.query(IdentityMapping).filter(IdentityMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Identity mapping not found")

    source_ids = _get_project_source_ids(db, mapping.project_id)

    if update_data.action == "confirm":
        target_user_id = update_data.mapped_user_id or mapping.mapped_user_id
        if not target_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot confirm identity mapping without a selected HandoffScope user",
            )
        mapping.mapped_user_id = target_user_id
        mapping.confidence = IdentityConfidence.VERIFIED
        mapping.verified_by = actor_id

        # Update matching source_records
        if source_ids:
            db.query(SourceRecord).filter(
                SourceRecord.connected_source_id.in_(source_ids),
                SourceRecord.author_external_id == mapping.external_username,
            ).update(
                {SourceRecord.author_mapped_user_id: target_user_id},
                synchronize_session=False,
            )

        create_audit_event(
            db,
            actor_id=actor_id,
            action="IDENTITY_MAPPING_VERIFIED",
            entity_type="identity_mapping",
            entity_id=mapping.id,
            details={
                "external_username": mapping.external_username,
                "mapped_user_id": str(target_user_id),
            },
            summary=f"Confirmed and verified mapping for {mapping.external_username}",
        )

    elif update_data.action == "reject":
        mapping.confidence = IdentityConfidence.UNMATCHED
        mapping.mapped_user_id = None
        mapping.verified_by = None

        # Clear matching source_records
        if source_ids:
            db.query(SourceRecord).filter(
                SourceRecord.connected_source_id.in_(source_ids),
                SourceRecord.author_external_id == mapping.external_username,
            ).update(
                {SourceRecord.author_mapped_user_id: None},
                synchronize_session=False,
            )

        create_audit_event(
            db,
            actor_id=actor_id,
            action="IDENTITY_MAPPING_REJECTED",
            entity_type="identity_mapping",
            entity_id=mapping.id,
            details={"external_username": mapping.external_username},
            summary=f"Rejected identity mapping for {mapping.external_username}",
        )

    elif update_data.action == "remap":
        mapping.mapped_user_id = update_data.mapped_user_id
        mapping.confidence = IdentityConfidence.SUGGESTED
        mapping.verified_by = None

        create_audit_event(
            db,
            actor_id=actor_id,
            action="IDENTITY_MAPPING_REMAPPED",
            entity_type="identity_mapping",
            entity_id=mapping.id,
            details={
                "external_username": mapping.external_username,
                "mapped_user_id": str(update_data.mapped_user_id) if update_data.mapped_user_id else None,
            },
            summary=f"Remapped {mapping.external_username} to user {update_data.mapped_user_id}",
        )

    db.commit()
    db.refresh(mapping)

    items = list_mappings(db, mapping.project_id)
    return next(i for i in items if i.id == mapping.id)


def get_coverage(db: Session, project_id: uuid.UUID) -> IdentityCoverageOut:
    """Calculate identity mapping coverage statistics for a project."""
    mappings = db.query(IdentityMapping).filter(IdentityMapping.project_id == project_id).all()
    source_ids = _get_project_source_ids(db, project_id)

    verified_count = sum(1 for m in mappings if m.confidence == IdentityConfidence.VERIFIED)
    suggested_count = sum(1 for m in mappings if m.confidence == IdentityConfidence.SUGGESTED)
    unmatched_count = sum(1 for m in mappings if m.confidence == IdentityConfidence.UNMATCHED)

    total_records = 0
    mapped_records = 0

    if source_ids:
        total_records = (
            db.query(func.count(SourceRecord.id))
            .filter(SourceRecord.connected_source_id.in_(source_ids))
            .scalar()
            or 0
        )
        mapped_records = (
            db.query(func.count(SourceRecord.id))
            .filter(
                SourceRecord.connected_source_id.in_(source_ids),
                SourceRecord.author_mapped_user_id.isnot(None),
            )
            .scalar()
            or 0
        )

    coverage_percent = round((mapped_records / total_records * 100), 1) if total_records > 0 else 0.0

    return IdentityCoverageOut(
        project_id=project_id,
        total_external_authors=len(mappings),
        verified_count=verified_count,
        suggested_count=suggested_count,
        unmatched_count=unmatched_count,
        total_source_records=total_records,
        mapped_source_records=mapped_records,
        coverage_percent=coverage_percent,
    )
