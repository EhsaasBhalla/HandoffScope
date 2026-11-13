"""Compliance export service — version-pinned, clearance-filtered PDF & signed ZIP bundles."""

from __future__ import annotations

import copy
import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.dependencies import get_user_context_capabilities, require_case_capability
from app.core.exceptions import ForbiddenError, HandoffScopeError
from app.db.enums import CaseParticipantRole, CaseStatus
from app.modules.audit.models import AuditEvent
from app.modules.audit.service import create_audit_event
from app.modules.evidence.clearance import (
    RESTRICTED_EVIDENCE_PLACEHOLDER,
    has_restricted_clearance,
)
from app.modules.sharing.redactor import redact_secrets_inline
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.projects.models import Project
from app.modules.recipients.models import RecipientAcknowledgement, ResponsibilityAssignment
from app.modules.recipients.service import _validate_and_parse_canonical_snapshot
from app.modules.reviews.models import HandoverVersion
from app.modules.reviews.service import SnapshotIntegrityError, compute_snapshot_hash
from app.modules.sharing.models import ShareGrant
from app.modules.workspaces.models import User

from app.modules.exports.crypto import (
    canonical_json_bytes,
    get_signing_material,
    sha256_hex,
    sign_manifest_bytes,
)
from app.modules.exports.pdf import render_handover_certificate_pdf
from app.modules.exports.verifier import STANDALONE_VERIFY_SCRIPT

EXPORTABLE_CASE_STATUSES = {
    CaseStatus.APPROVED,
    CaseStatus.SHARED,
    CaseStatus.PARTIALLY_ACKNOWLEDGED,
    CaseStatus.ACKNOWLEDGED,
    CaseStatus.TRANSFERRED,
}

BUNDLE_FORMAT = "handoffscope-compliance-bundle"
BUNDLE_FORMAT_VERSION = 1


class ExportStateError(HandoffScopeError):
    """Raised when a case or version is not eligible for compliance certification."""


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_slug(text: str, fallback: str = "pack") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", (text or "").strip().lower()).strip("-")
    return (cleaned[:48] or fallback)


def _authorize_and_resolve_version(
    db: Session,
    *,
    case_id: uuid.UUID,
    user: User,
    version_id: Optional[uuid.UUID] = None,
    version_number: Optional[int] = None,
) -> tuple[HandoverCase, Project, HandoverVersion, bool]:
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise ValueError("Handover case not found")

    project = db.query(Project).filter(Project.id == case.project_id).first()
    if not project:
        raise ValueError("Parent project not found")

    # Verify user has case.view OR active share grant/recipient participation
    caps, _, _ = get_user_context_capabilities(db, user, case_id=case_id)
    has_share_access = (
        db.query(ShareGrant)
        .join(HandoverVersion, ShareGrant.handover_version_id == HandoverVersion.id)
        .filter(
            HandoverVersion.case_id == case_id,
            ShareGrant.recipient_user_id == user.id,
            ShareGrant.revoked_at.is_(None),
        )
        .first()
        is not None
    )
    if "case.view" not in caps and not has_share_access:
        raise ForbiddenError("Not authorized to export this handover case")

    # Never certify unapproved drafts
    if case.status not in EXPORTABLE_CASE_STATUSES:
        raise ExportStateError(
            f"Compliance export requires an approved handover case (current status: {case.status.value})."
        )

    v_q = db.query(HandoverVersion).filter(HandoverVersion.case_id == case_id)
    if version_id is not None:
        version = v_q.filter(HandoverVersion.id == version_id).first()
    elif version_number is not None:
        version = v_q.filter(HandoverVersion.version_number == version_number).first()
    else:
        version = (
            v_q.filter(HandoverVersion.is_current.is_(True)).first()
            or v_q.order_by(HandoverVersion.version_number.desc()).first()
        )

    if not version:
        raise ExportStateError("No approved handover version exists for this case.")

    allow_restricted = has_restricted_clearance(
        db,
        user_id=user.id,
        project_id=case.project_id,
        case_id=case.id,
        user=user,
    )
    return case, project, version, allow_restricted


def _build_clearance_filtered_projection(
    db: Session,
    *,
    case: HandoverCase,
    project: Project,
    version: HandoverVersion,
    user: User,
    allow_restricted: bool,
    generated_at: str,
) -> dict[str, Any]:
    """Assemble deterministic, clearance-filtered projection strictly from frozen snapshot_json."""
    snap = version.snapshot_json
    if not isinstance(snap, dict):
        raise SnapshotIntegrityError("Approved version snapshot is missing or corrupted.")

    if "transfer_packs" in snap or snap.get("schema_version", 0) >= 2:
        raw_packs, raw_next_actions, raw_unfinished = _validate_and_parse_canonical_snapshot(snap)
        snap_hash = (snap.get("metadata") or {}).get("snapshot_hash") or compute_snapshot_hash(snap)
    else:
        raise SnapshotIntegrityError(
            "Approved version snapshot predates canonical schema and cannot be compliance-certified."
        )

    filtered_snapshot = copy.deepcopy(snap)
    filtered_packs: list[dict[str, Any]] = []
    redacted_claims_count = 0
    redacted_evidence_count = 0
    total_claims = 0

    for pack in copy.deepcopy(raw_packs):
        clean_claims: list[dict[str, Any]] = []
        for claim in pack.get("claims", []):
            total_claims += 1
            ev_list = claim.get("evidence") or []
            claim_has_restricted = False
            filtered_ev_list: list[dict[str, Any]] = []
            for ev in ev_list:
                if not isinstance(ev, dict):
                    continue
                ev_copy = dict(ev)
                if ev_copy.get("is_restricted") and not allow_restricted:
                    claim_has_restricted = True
                    redacted_evidence_count += 1
                    ev_copy["excerpt"] = "[WITHHELD BY ACCESS POLICY]"
                    ev_copy["locator"] = "Restricted Document Reference"
                    ev_copy["source_record_id"] = None
                    ev_copy["document_id"] = None
                elif not allow_restricted and ev_copy.get("excerpt"):
                    ev_copy["excerpt"] = redact_secrets_inline(str(ev_copy["excerpt"])).redacted_text
                filtered_ev_list.append(ev_copy)

            if claim_has_restricted and not allow_restricted:
                redacted_claims_count += 1
                claim["body_text"] = RESTRICTED_EVIDENCE_PLACEHOLDER
                claim["original_body_text"] = None
                claim["review_notes"] = None
            elif not allow_restricted:
                if claim.get("body_text"):
                    claim["body_text"] = redact_secrets_inline(str(claim["body_text"])).redacted_text
                if claim.get("original_body_text"):
                    claim["original_body_text"] = redact_secrets_inline(str(claim["original_body_text"])).redacted_text
            claim["evidence"] = filtered_ev_list
            clean_claims.append(claim)
        pack["claims"] = clean_claims
        filtered_packs.append(pack)

    filtered_snapshot["transfer_packs"] = filtered_packs

    # Filter unfinished items and next actions consistently
    filtered_next_actions: list[dict[str, Any]] = []
    for p in filtered_packs:
        for c in p.get("claims", []):
            if c.get("claim_type") == "NEXT_ACTION":
                filtered_next_actions.append(c)
    filtered_snapshot["next_actions"] = filtered_next_actions

    filtered_unfinished: list[dict[str, Any]] = []
    for item in raw_unfinished or []:
        if not isinstance(item, dict):
            continue
        item_copy = dict(item)
        if item_copy.get("is_restricted") and not allow_restricted:
            item_copy["description"] = RESTRICTED_EVIDENCE_PLACEHOLDER
            item_copy.pop("is_restricted", None)
        filtered_unfinished.append(item_copy)
    if not raw_unfinished:
        for p in filtered_packs:
            for c in p.get("claims", []):
                if c.get("claim_type") in ("KNOWLEDGE_GAP", "RISK"):
                    filtered_unfinished.append({
                        "id": c.get("id"),
                        "type": "CLAIM",
                        "title": c.get("title"),
                        "description": c.get("body_text"),
                        "priority": c.get("priority", "MEDIUM"),
                    })
    filtered_snapshot["unfinished_items"] = filtered_unfinished

    # Export-time acknowledgements & responsibility assignments (explicitly stamped as export-time attestation)
    acks = (
        db.query(RecipientAcknowledgement)
        .filter(RecipientAcknowledgement.handover_version_id == version.id)
        .order_by(RecipientAcknowledgement.acknowledged_at.asc(), RecipientAcknowledgement.id.asc())
        .all()
    )
    ack_payload = []
    for a in acks:
        u = a.user or db.query(User).filter(User.id == a.user_id).first()
        ack_payload.append({
            "id": str(a.id),
            "handover_version_id": str(a.handover_version_id),
            "user_id": str(a.user_id),
            "user_name": u.display_name if u else "Unknown",
            "user_email": u.email if u else None,
            "acknowledged_at": _iso_utc(a.acknowledged_at),
        })

    assigns = (
        db.query(ResponsibilityAssignment)
        .filter(ResponsibilityAssignment.handover_version_id == version.id)
        .order_by(ResponsibilityAssignment.assigned_at.asc(), ResponsibilityAssignment.id.asc())
        .all()
    )
    assign_payload = []
    for asgn in assigns:
        acc = asgn.acceptance
        assign_payload.append({
            "id": str(asgn.id),
            "transfer_pack_id": str(asgn.transfer_pack_id),
            "transfer_pack_name": asgn.transfer_pack.name if asgn.transfer_pack else "Transfer Pack",
            "handover_version_id": str(asgn.handover_version_id),
            "assigned_user_id": str(asgn.assigned_user_id),
            "assignee_name": asgn.assignee.display_name if asgn.assignee else "Unknown",
            "assigned_at": _iso_utc(asgn.assigned_at),
            "status": acc.status.value if acc and hasattr(acc.status, "value") else "PENDING_ACCEPTANCE",
            "responded_at": _iso_utc(acc.responded_at) if acc and acc.responded_at else None,
            "decline_reason": acc.decline_reason if acc else None,
        })

    # Sanitized audit log slice scoped cleanly to the case
    audit_rows = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.entity_id == case.id,
        )
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .limit(300)
        .all()
    )
    audit_payload = []
    for ev in audit_rows:
        details_safe = dict(ev.details or {}) if isinstance(ev.details, dict) else {}
        if not allow_restricted:
            for sensitive_k in ("excerpt", "body", "secret", "token", "override_details"):
                details_safe.pop(sensitive_k, None)
        audit_payload.append({
            "id": str(ev.id),
            "action": ev.action,
            "entity_type": ev.entity_type,
            "entity_id": str(ev.entity_id),
            "actor_id": str(ev.actor_id) if ev.actor_id else None,
            "summary": ev.summary if allow_restricted else (
                "[WITHHELD BY ACCESS POLICY]" if "restricted" in (ev.summary or "").lower() else ev.summary
            ),
            "created_at": _iso_utc(ev.created_at),
            "details": details_safe,
        })

    export_scope = "INTERNAL_FULL" if allow_restricted else "RECIPIENT_SAFE"
    approver_name = (
        version.approver.display_name
        if version.approver
        else (snap.get("metadata") or {}).get("approved_by_name") or "Reviewer"
    )
    override_meta = snap.get("override_metadata") if allow_restricted or not snap.get("override_metadata") else {
        "override_by_name": snap["override_metadata"].get("override_by_name"),
        "override_at": snap["override_metadata"].get("override_at"),
        "override_justification": snap["override_metadata"].get("override_justification"),
    }

    return {
        "format_version": BUNDLE_FORMAT_VERSION,
        "case_id": str(case.id),
        "case_number": case.case_number,
        "case_title": case.title,
        "case_status": case.status.value,
        "sync_status": case.sync_status.value,
        "project_id": str(project.id),
        "project_name": project.name,
        "version_id": str(version.id),
        "version_number": version.version_number,
        "snapshot_schema_version": snap.get("schema_version", 2),
        "snapshot_hash": snap_hash,
        "approved_by_name": approver_name,
        "approved_at": _iso_utc(version.approved_at),
        "amendment_reason": version.amendment_reason,
        "exported_by_id": str(user.id),
        "exported_by_name": user.display_name,
        "exported_by_email": user.email,
        "export_scope": export_scope,
        "generated_at": generated_at,
        "redacted_claims_count": redacted_claims_count,
        "redacted_evidence_count": redacted_evidence_count,
        "transfer_packs": filtered_packs,
        "unfinished_items": filtered_unfinished,
        "override_metadata": override_meta,
        "overridden_unresolved_items": snap.get("overridden_unresolved_items") or [] if allow_restricted else [],
        "filtered_snapshot": filtered_snapshot,
        "acknowledgements": ack_payload,
        "responsibility_assignments": assign_payload,
        "audit_log": audit_payload,
        "summary": {
            "total_packs": len(filtered_packs),
            "total_claims": total_claims,
            "total_gaps": len(filtered_unfinished),
            "total_next_actions": len(filtered_next_actions),
        },
    }


def _render_pack_markdown(pack: dict[str, Any], projection: dict[str, Any]) -> str:
    lines = [
        f"# Transfer Pack: {pack.get('name')}",
        "",
        f"- **Case:** #{projection['case_number']} — {projection['case_title']}",
        f"- **Approved Version:** v{projection['version_number']} (`{projection['version_id']}`)",
        f"- **Component Area:** {pack.get('component_area') or 'General'}",
        f"- **Export Scope:** `{projection['export_scope']}`",
        "",
    ]
    if pack.get("description"):
        lines.extend([pack["description"], ""])
    lines.append("## Claims & Verification")
    lines.append("")
    for idx, c in enumerate(pack.get("claims", []), 1):
        lines.append(f"### {idx}. {c.get('title')}")
        lines.append(
            f"- **Type:** `{c.get('claim_type')}` | **Evidence:** `{c.get('evidence_state')}` | "
            f"**Review:** `{c.get('review_state')}` | **Priority:** `{c.get('priority', 'MEDIUM')}`"
        )
        lines.append("")
        lines.append(c.get("body_text") or "_No description_")
        lines.append("")
        evs = c.get("evidence") or []
        if evs:
            lines.append("**Citations:**")
            for ev in evs:
                loc = ev.get("locator") or ev.get("evidence_type") or "Evidence"
                lines.append(f"- `{loc}`")
            lines.append("")
    return "\n".join(lines)


def generate_certificate_pdf(
    db: Session,
    *,
    case_id: uuid.UUID,
    user: User,
    version_id: Optional[uuid.UUID] = None,
    version_number: Optional[int] = None,
) -> tuple[bytes, str, HandoverVersion]:
    """Generate a clearance-filtered Executive Handover Certificate PDF."""
    case, project, version, allow_restricted = _authorize_and_resolve_version(
        db,
        case_id=case_id,
        user=user,
        version_id=version_id,
        version_number=version_number,
    )
    generated_at = _iso_utc(datetime.now(timezone.utc))
    projection = _build_clearance_filtered_projection(
        db,
        case=case,
        project=project,
        version=version,
        user=user,
        allow_restricted=allow_restricted,
        generated_at=generated_at,
    )
    material = get_signing_material()
    signer_info = {
        "algorithm": "Ed25519",
        "signing_key_id": material.key_id,
        "public_key_fingerprint": material.public_key_fingerprint,
        "persistent_key_configured": material.persistent_configured,
    }
    pdf_bytes = render_handover_certificate_pdf(projection=projection, signer_info=signer_info)
    filename = f"handoff-case-{case.case_number}-v{version.version_number}-certificate.pdf"

    create_audit_event(
        db,
        actor_id=user.id,
        action="export.certificate_pdf_generated",
        entity_type="handover_case",
        entity_id=case.id,
        details={
            "handover_version_id": str(version.id),
            "version_number": version.version_number,
            "export_scope": projection["export_scope"],
            "redacted_claims_count": projection["redacted_claims_count"],
        },
        summary=f"Exported Handover Certificate PDF for v{version.version_number} ({projection['export_scope']})",
    )
    db.commit()
    return pdf_bytes, filename, version


def generate_compliance_bundle_zip(
    db: Session,
    *,
    case_id: uuid.UUID,
    user: User,
    version_id: Optional[uuid.UUID] = None,
    version_number: Optional[int] = None,
) -> tuple[bytes, str, HandoverVersion]:
    """Build a clearance-filtered, SHA-256-manifested, Ed25519-signed offline ZIP archive."""
    case, project, version, allow_restricted = _authorize_and_resolve_version(
        db,
        case_id=case_id,
        user=user,
        version_id=version_id,
        version_number=version_number,
    )
    generated_at = _iso_utc(datetime.now(timezone.utc))
    projection = _build_clearance_filtered_projection(
        db,
        case=case,
        project=project,
        version=version,
        user=user,
        allow_restricted=allow_restricted,
        generated_at=generated_at,
    )
    material = get_signing_material()
    signer_info = {
        "algorithm": "Ed25519",
        "signing_key_id": material.key_id,
        "public_key_fingerprint": material.public_key_fingerprint,
        "persistent_key_configured": material.persistent_configured,
    }

    # Build PDF first; failure here aborts export cleanly so partial ZIP is never produced
    pdf_bytes = render_handover_certificate_pdf(projection=projection, signer_info=signer_info)

    snapshot_export = {
        "handover_version_id": projection["version_id"],
        "handover_version_number": projection["version_number"],
        "export_scope": projection["export_scope"],
        "canonical_snapshot_hash": projection["snapshot_hash"],
        "snapshot": projection["filtered_snapshot"],
    }
    ack_export = {
        "attestation_type": "export_time_snapshot_of_version_acknowledgements",
        "attestation_captured_at": generated_at,
        "handover_version_id": projection["version_id"],
        "handover_version_number": projection["version_number"],
        "acknowledgements": projection["acknowledgements"],
    }
    assign_export = {
        "attestation_type": "export_time_snapshot_of_responsibility_assignments",
        "attestation_captured_at": generated_at,
        "handover_version_id": projection["version_id"],
        "handover_version_number": projection["version_number"],
        "responsibility_assignments": projection["responsibility_assignments"],
    }
    audit_export = {
        "case_id": projection["case_id"],
        "export_scope": projection["export_scope"],
        "captured_at": generated_at,
        "events": projection["audit_log"],
    }

    readme_md = "\n".join([
        "# HandoffScope Offline Compliance Bundle Verification",
        "",
        f"- **Project:** {projection['project_name']}",
        f"- **Case:** #{projection['case_number']} — {projection['case_title']} (`{projection['case_id']}`)",
        f"- **Approved Version:** v{projection['version_number']} (`{projection['version_id']}`)",
        f"- **Export Scope:** `{projection['export_scope']}`",
        f"- **Signing Key ID:** `{material.key_id}`",
        f"- **Public Key Fingerprint:** `{material.public_key_fingerprint}`",
        "",
        "## Offline Verification",
        "```bash",
        "python verify_bundle.py <this-bundle.zip> [expected_trusted_fingerprint]",
        "```",
        "",
        "Note: `public_key.pem` inside this archive verifies internal integrity and signature consistency.",
        "Compare `public_key_fingerprint` against `/api/v1/exports/signing-key` on your HandoffScope server",
        "to confirm trusted signer identity.",
    ])

    files_to_package: list[tuple[str, str, bytes]] = [
        ("certificate.pdf", "application/pdf", pdf_bytes),
        ("snapshot.json", "application/json", canonical_json_bytes(snapshot_export)),
        ("acknowledgements.json", "application/json", canonical_json_bytes(ack_export)),
        ("responsibility_assignments.json", "application/json", canonical_json_bytes(assign_export)),
        ("audit_log.json", "application/json", canonical_json_bytes(audit_export)),
        ("README_VERIFY.md", "text/markdown", readme_md.encode("utf-8")),
        ("verify_bundle.py", "text/x-python", STANDALONE_VERIFY_SCRIPT.encode("utf-8")),
    ]

    used_pack_names: set[str] = set()
    for idx, p in enumerate(projection["transfer_packs"], 1):
        slug = _safe_slug(str(p.get("name") or ""), fallback=f"pack-{idx}")
        candidate = f"transfer-packs/{idx:02d}-{slug}.md"
        while candidate in used_pack_names:
            candidate = f"transfer-packs/{idx:02d}-{slug}-{len(used_pack_names)}.md"
        used_pack_names.add(candidate)
        md_bytes = _render_pack_markdown(p, projection).encode("utf-8")
        files_to_package.append((candidate, "text/markdown", md_bytes))

    manifest = {
        "format": BUNDLE_FORMAT,
        "format_version": BUNDLE_FORMAT_VERSION,
        "case_id": projection["case_id"],
        "project_id": projection["project_id"],
        "handover_version_id": projection["version_id"],
        "handover_version_number": projection["version_number"],
        "snapshot_schema_version": projection["snapshot_schema_version"],
        "snapshot_sha256": projection["snapshot_hash"],
        "export_scope": projection["export_scope"],
        "generated_at": generated_at,
        "exported_by": {
            "user_id": projection["exported_by_id"],
            "display_name": projection["exported_by_name"],
        },
        "algorithm": "Ed25519",
        "signing_key_id": material.key_id,
        "public_key_fingerprint": material.public_key_fingerprint,
        "artifacts": [
            {
                "path": path,
                "media_type": media_type,
                "size_bytes": len(content),
                "sha256": sha256_hex(content),
            }
            for path, media_type, content in files_to_package
        ],
    }

    manifest_bytes = canonical_json_bytes(manifest)
    sig_envelope = sign_manifest_bytes(manifest_bytes)
    sig_bytes = canonical_json_bytes(sig_envelope)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, _, content in files_to_package:
            zf.writestr(path, content)
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("certificate.sig", sig_bytes)
        zf.writestr("public_key.pem", material.public_key_pem)

    zip_bytes = zip_buf.getvalue()
    zip_filename = f"handoff-case-{case.case_number}-v{version.version_number}-compliance-bundle.zip"

    create_audit_event(
        db,
        actor_id=user.id,
        action="export.compliance_bundle_generated",
        entity_type="handover_case",
        entity_id=case.id,
        details={
            "handover_version_id": str(version.id),
            "version_number": version.version_number,
            "export_scope": projection["export_scope"],
            "redacted_claims_count": projection["redacted_claims_count"],
            "manifest_sha256": sig_envelope["manifest_sha256"],
            "signing_key_id": material.key_id,
        },
        summary=f"Exported signed compliance archive for v{version.version_number} ({projection['export_scope']})",
    )
    db.commit()
    return zip_bytes, zip_filename, version
