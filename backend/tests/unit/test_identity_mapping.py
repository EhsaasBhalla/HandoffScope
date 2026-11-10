"""Unit tests for Phase 5 — Identity mapping and coverage."""

import uuid
import pytest
from app.db.base import SessionLocal
from app.db.enums import IdentityConfidence
from app.modules.identity import service
from app.modules.identity.schemas import IdentityMappingCreate, IdentityMappingUpdate
from app.modules.projects.models import Project
from app.modules.workspaces.models import User


def test_identity_mapping_lifecycle():
    db = SessionLocal()
    try:
        project = db.query(Project).first()
        assert project is not None, "At least one project should be seeded"

        # 1. Run auto suggest
        suggestions = service.auto_suggest_mappings(db, project.id)
        assert len(suggestions) > 0

        # Find any suggestion
        target = suggestions[0]
        assert target.external_username is not None

        # 2. Confirm mapping
        user = db.query(User).first()
        updated = service.update_mapping(
            db,
            target.id,
            actor_id=user.id,
            update_data=IdentityMappingUpdate(action="confirm", mapped_user_id=user.id),
        )
        assert updated.confidence == IdentityConfidence.VERIFIED
        assert updated.mapped_user_id == user.id

        # 3. Check coverage
        coverage = service.get_coverage(db, project.id)
        assert coverage.verified_count >= 1
        assert coverage.total_external_authors >= 1

        # 4. Reject mapping
        rejected = service.update_mapping(
            db,
            target.id,
            actor_id=user.id,
            update_data=IdentityMappingUpdate(action="reject"),
        )
        assert rejected.confidence == IdentityConfidence.UNMATCHED
        assert rejected.mapped_user_id is None
    finally:
        db.close()
