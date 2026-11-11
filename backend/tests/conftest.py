"""Pytest session isolation, additive schema guard, and deterministic demo seeding."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

import pytest

_TEST_DB_DIR = tempfile.TemporaryDirectory(prefix="handoffscope_pytest_")
_TEST_DB_PATH = Path(_TEST_DB_DIR.name) / "test_handoffscope.db"
_TEST_UPLOAD_DIR = Path(_TEST_DB_DIR.name) / "uploads"
_TEST_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def pytest_configure(config):
    """Route pytest runs to a fresh hermetic SQLite DB so dev handoffscope.db stays clean."""
    current_url = os.environ.get("DATABASE_URL", "")
    if not current_url or "sqlite" in current_url:
        os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"
    os.environ.setdefault("UPLOAD_DIR", str(_TEST_UPLOAD_DIR))


def pytest_sessionfinish(session, exitstatus):
    """Dispose SQLAlchemy engine and remove temporary pytest database cleanly."""
    try:
        from app.db.base import engine

        engine.dispose()
    except Exception:
        pass
    try:
        _TEST_DB_DIR.cleanup()
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def ensure_test_database_schema():
    """Apply additive schema columns and seed initial demo data on the fresh pytest DB."""
    from app.db.base import SessionLocal, engine
    from app.db.schema_guard import ensure_additive_schema

    ensure_additive_schema(engine)
    db = SessionLocal()
    try:
        from app.modules.workspaces.models import User

        if db.query(User).count() == 0:
            from app.seed.demo_seed import seed_demo_data

            seed_demo_data(db)
    finally:
        db.close()
