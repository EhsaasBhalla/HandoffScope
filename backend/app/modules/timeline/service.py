"""Timeline service — aggregate source records, source events, and audit actions into a unified timeline."""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.enums import Sensitivity, SourceRecordType
from app.modules.audit.models import AuditEvent
from app.modules.handover_cases.models import HandoverCase
from app.modules.identity.models import IdentityMapping
from app.modules.ingestion.models import SourceEvent, SourceRecord


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
from app.modules.sources.models import ConnectedSource
from app.modules.timeline.schemas import GitCommitOut, GitHistoryResponse, TimelineItemOut, TimelineResponse
from app.modules.workspaces.models import User


def get_project_timeline(
    db: Session,
    project_id: uuid.UUID,
    *,
    event_type: str | None = None,
    actor: str | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    per_page: int = 30,
) -> TimelineResponse:
    """Fetch and aggregate chronological events for a project across all its sources and audit trails."""
    # 1. Sources connected to this project
    sources = db.query(ConnectedSource).filter(ConnectedSource.project_id == project_id).all()
    source_ids = [s.id for s in sources]
    sources_map = {s.id: s for s in sources}

    # Pre-load users for display name lookup
    users = db.query(User).all()
    users_map = {u.id: u for u in users}

    raw_items: list[TimelineItemOut] = []

    # 2. Ingest SourceRecords (Commits, Issues, PRs, Documents)
    if source_ids:
        records = (
            db.query(SourceRecord)
            .filter(SourceRecord.connected_source_id.in_(source_ids))
            .all()
        )

        for rec in records:
            src = sources_map.get(rec.connected_source_id)
            src_name = src.name if src else "Source"
            src_type_val = src.source_type.value if src else "github"

            mapped_user = users_map.get(rec.author_mapped_user_id) if rec.author_mapped_user_id else None
            mapped_user_name = mapped_user.display_name if mapped_user else None

            # Determine type & label
            if rec.record_type == SourceRecordType.COMMIT:
                ev_type = "COMMIT"
                title = rec.title or f"Commit {rec.external_id[:8]}"
            elif rec.record_type == SourceRecordType.PR:
                ev_type = "PULL_REQUEST"
                title = f"PR #{rec.external_id}: {rec.title or 'Untitled Pull Request'}"
            elif rec.record_type == SourceRecordType.ISSUE:
                ev_type = "ISSUE"
                title = f"Issue #{rec.external_id}: {rec.title or 'Untitled Issue'}"
            else:
                ev_type = rec.record_type.value
                title = rec.title or f"{rec.record_type.value} #{rec.external_id}"

            item_time = _to_utc(rec.external_created_at or rec.created_at)
            rec_summary = (
                "[RESTRICTED CONTENT WITHHELD]"
                if getattr(rec, "sensitivity", None) == Sensitivity.RESTRICTED
                else rec.body
            )

            raw_items.append(
                TimelineItemOut(
                    id=f"sr-{rec.id}",
                    timestamp=item_time,
                    event_type=ev_type,
                    title=title,
                    summary=rec_summary,
                    actor_name=rec.author_name or rec.author_external_id,
                    actor_external_id=rec.author_external_id,
                    actor_mapped_user_id=rec.author_mapped_user_id,
                    actor_mapped_user_name=mapped_user_name,
                    source_name=src_name,
                    source_type=src_type_val,
                    url=rec.url,
                    metadata={
                        "state": rec.state,
                        "external_id": rec.external_id,
                        "record_type": rec.record_type.value,
                    },
                )
            )

        # 3. Ingest SourceEvents (Comments, Reviews, state transitions)
        record_ids = [r.id for r in records]
        if record_ids:
            events = (
                db.query(SourceEvent)
                .filter(SourceEvent.record_id.in_(record_ids))
                .all()
            )
            records_map = {r.id: r for r in records}

            for ev in events:
                parent_rec = records_map.get(ev.record_id)
                parent_title = parent_rec.title if parent_rec else ""
                parent_num = parent_rec.external_id if parent_rec else ""
                src = sources_map.get(parent_rec.connected_source_id) if parent_rec else None

                mapped_user = (
                    users_map.get(parent_rec.author_mapped_user_id)
                    if parent_rec and parent_rec.author_mapped_user_id
                    else None
                )

                ev_type_label = f"SOURCE_{ev.event_type.upper()}"
                item_time = _to_utc(ev.occurred_at or (parent_rec.created_at if parent_rec else datetime.now(timezone.utc)))

                raw_items.append(
                    TimelineItemOut(
                        id=f"se-{ev.id}",
                        timestamp=item_time,
                        event_type=ev_type_label,
                        title=f"{ev.event_type.title()} on #{parent_num} ({parent_title[:40]}...)",
                        summary=ev.body,
                        actor_name=ev.author_name or ev.author_external_id,
                        actor_external_id=ev.author_external_id,
                        actor_mapped_user_id=parent_rec.author_mapped_user_id if parent_rec else None,
                        actor_mapped_user_name=mapped_user.display_name if mapped_user else None,
                        source_name=src.name if src else "Source",
                        source_type=src.source_type.value if src else "github",
                        url=parent_rec.url if parent_rec else None,
                        metadata=ev.metadata_json or {},
                    )
                )

    # 4. Ingest AuditEvents (Project & Case governance events scoped strictly to this project)
    case_ids = [c.id for c in db.query(HandoverCase.id).filter(HandoverCase.project_id == project_id).all()]
    mapping_ids = [m.id for m in db.query(IdentityMapping.id).filter(IdentityMapping.project_id == project_id).all()]

    filters = [(AuditEvent.entity_type == "project") & (AuditEvent.entity_id == project_id)]
    if case_ids:
        filters.append((AuditEvent.entity_type == "handover_case") & (AuditEvent.entity_id.in_(case_ids)))
    if source_ids:
        filters.append((AuditEvent.entity_type == "connected_source") & (AuditEvent.entity_id.in_(source_ids)))
    if mapping_ids:
        filters.append((AuditEvent.entity_type == "identity_mapping") & (AuditEvent.entity_id.in_(mapping_ids)))

    from sqlalchemy import or_
    audits = db.query(AuditEvent).filter(or_(*filters)).all()

    for aud in audits:
        actor_user = users_map.get(aud.actor_id) if aud.actor_id else None
        raw_items.append(
            TimelineItemOut(
                id=f"audit-{aud.id}",
                timestamp=_to_utc(aud.created_at),
                event_type="AUDIT",
                title=aud.summary or f"Audit: {aud.action}",
                summary=f"Action: {aud.action} on {aud.entity_type}",
                actor_name=actor_user.display_name if actor_user else "System",
                actor_external_id=None,
                actor_mapped_user_id=aud.actor_id,
                actor_mapped_user_name=actor_user.display_name if actor_user else None,
                source_name="Audit Log",
                source_type="system",
                url=None,
                metadata=aud.details or {},
            )
        )

    # 5. Collect available event types before filtering
    available_event_types = sorted(list({item.event_type for item in raw_items}))

    # 6. Apply Filters
    filtered = raw_items

    if event_type:
        types_requested = {t.strip().upper() for t in event_type.split(",")}
        filtered = [i for i in filtered if i.event_type.upper() in types_requested]

    if actor:
        q_actor = actor.lower().strip()
        filtered = [
            i
            for i in filtered
            if (i.actor_name and q_actor in i.actor_name.lower())
            or (i.actor_external_id and q_actor in i.actor_external_id.lower())
            or (i.actor_mapped_user_name and q_actor in i.actor_mapped_user_name.lower())
        ]

    if search:
        q_search = search.lower().strip()
        filtered = [
            i
            for i in filtered
            if (i.title and q_search in i.title.lower())
            or (i.summary and q_search in i.summary.lower())
        ]

    date_from_utc = _to_utc(date_from)
    date_to_utc = _to_utc(date_to)
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    if date_from_utc:
        filtered = [i for i in filtered if (_to_utc(i.timestamp) or min_dt) >= date_from_utc]

    if date_to_utc:
        filtered = [i for i in filtered if (_to_utc(i.timestamp) or min_dt) <= date_to_utc]

    # 7. Sort reverse chronological
    filtered.sort(key=lambda x: _to_utc(x.timestamp) or min_dt, reverse=True)

    # 8. Pagination
    total = len(filtered)
    total_pages = math.ceil(total / per_page) if per_page > 0 else 1
    offset = (page - 1) * per_page
    paginated_items = filtered[offset : offset + per_page]

    return TimelineResponse(
        items=paginated_items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        event_types=available_event_types,
    )


def get_project_git_history(
    db: Session,
    project_id: uuid.UUID,
    *,
    search: str | None = None,
    author: str | None = None,
    source_id: uuid.UUID | None = None,
    page: int = 1,
    per_page: int = 30,
) -> GitHistoryResponse:
    """Fetch paginated, chronological git commits for a project across its connected repositories."""
    sources_query = db.query(ConnectedSource).filter(ConnectedSource.project_id == project_id)
    if source_id:
        sources_query = sources_query.filter(ConnectedSource.id == source_id)
    sources = sources_query.all()
    source_ids = [s.id for s in sources]
    sources_map = {s.id: s for s in sources}

    if not source_ids:
        return GitHistoryResponse(items=[], total=0, page=page, per_page=per_page, total_pages=1)

    # Pre-load users for display name lookup
    users = db.query(User).all()
    users_map = {u.id: u for u in users}

    records = (
        db.query(SourceRecord)
        .filter(
            SourceRecord.connected_source_id.in_(source_ids),
            SourceRecord.record_type == SourceRecordType.COMMIT,
        )
        .all()
    )

    items: list[GitCommitOut] = []
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    for rec in records:
        src = sources_map.get(rec.connected_source_id)
        src_name = src.name if src else "Repository"
        meta = rec.metadata_json or {}

        mapped_user = users_map.get(rec.author_mapped_user_id) if rec.author_mapped_user_id else None
        mapped_user_name = mapped_user.display_name if mapped_user else None

        commit_dt = _to_utc(rec.external_created_at or rec.created_at)
        sha = rec.external_id or ""
        short_sha = sha[:7] if len(sha) >= 7 else sha

        title = rec.title or (rec.body.split("\n")[0] if rec.body else f"Commit {short_sha}")
        body_text = rec.body if rec.body and rec.body != title else None

        items.append(
            GitCommitOut(
                id=rec.id,
                sha=sha,
                short_sha=short_sha,
                title=title,
                message=body_text,
                author_name=rec.author_name or rec.author_external_id or "Unknown",
                author_external_id=rec.author_external_id,
                author_mapped_user_id=rec.author_mapped_user_id,
                author_mapped_user_name=mapped_user_name,
                committed_at=commit_dt,
                url=rec.url,
                source_id=rec.connected_source_id,
                source_name=src_name,
                branch=meta.get("branch") or meta.get("ref"),
                stats=meta.get("stats"),
                files=meta.get("files"),
            )
        )

    # Filtering
    if author:
        q_author = author.lower().strip()
        items = [
            i for i in items
            if (i.author_name and q_author in i.author_name.lower())
            or (i.author_external_id and q_author in i.author_external_id.lower())
            or (i.author_mapped_user_name and q_author in i.author_mapped_user_name.lower())
        ]

    if search:
        q_search = search.lower().strip()
        items = [
            i for i in items
            if (i.title and q_search in i.title.lower())
            or (i.message and q_search in i.message.lower())
            or (i.sha and q_search in i.sha.lower())
        ]

    # Sort reverse chronological by commit date
    items.sort(key=lambda x: _to_utc(x.committed_at) or min_dt, reverse=True)

    total = len(items)
    total_pages = math.ceil(total / per_page) if per_page > 0 else 1
    offset = (page - 1) * per_page
    paginated = items[offset : offset + per_page]

    return GitHistoryResponse(
        items=paginated,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )
