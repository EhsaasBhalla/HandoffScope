"""Maintenance CLI script for safe GitHub PR-as-ISSUE deduplication.

Usage examples:
    py -3.14 -m scripts.deduplicate_github_records --actor-email maya.sharma@example.test --dry-run
    py -3.14 -m scripts.deduplicate_github_records --actor-email maya.sharma@example.test --apply
    py -3.14 -m scripts.deduplicate_github_records --actor-email maya.sharma@example.test --source-id <UUID> --apply
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import SessionLocal, engine
from app.db.schema_guard import ensure_additive_schema
from app.modules.sources.service import cleanup_duplicate_github_records
from app.modules.workspaces.models import User


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or safely deduplicate historical GitHub PR-as-ISSUE records.",
    )
    parser.add_argument(
        "--actor-email",
        required=True,
        help="Email of the Lead or Workspace Owner authorizing this maintenance operation.",
    )
    parser.add_argument(
        "--source-id",
        default=None,
        help="Optional ConnectedSource UUID to restrict scanning/cleanup.",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Optional Project UUID to restrict scanning/cleanup.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report candidate duplicates and ambiguous records without deleting rows (default).",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Execute transactional re-linking and deletion of confirmed duplicate ISSUE rows.",
    )

    args = parser.parse_args(argv)
    dry_run = not args.apply

    ensure_additive_schema(engine)
    db = SessionLocal()
    try:
        actor = db.query(User).filter(User.email == args.actor_email.strip()).first()
        if not actor:
            print(json.dumps({"error": f"User not found: {args.actor_email}"}), file=sys.stderr)
            return 1

        src_uuid = uuid.UUID(args.source_id) if args.source_id else None
        proj_uuid = uuid.UUID(args.project_id) if args.project_id else None

        result = cleanup_duplicate_github_records(
            db,
            actor_id=actor.id,
            source_id=src_uuid,
            project_id=proj_uuid,
            dry_run=dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0
    except PermissionError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
