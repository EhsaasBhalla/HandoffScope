"""HandoffScope FastAPI application factory and entry point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text

from app.api.router import router as api_router
from app.core.constants import APP_NAME, VERSION
from app.core.exceptions import setup_exception_handlers
from app.core.logging import logger
from app.core.middleware import setup_middleware
from app.db.base import Base, SessionLocal, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager: sets up DB tables and seeds on first launch."""
    # Ensure all ORM models are registered
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

    try:
        # Ensure new columns exist on existing databases
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE source_records ADD COLUMN author_mapped_user_id VARCHAR(36)"))
                conn.commit()
            except Exception:
                pass

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            from app.modules.workspaces.models import User
            if db.query(User).count() == 0:
                logger.info("Fresh database detected — seeding demo data and synthetic fixture...")
                from app.seed.demo_seed import seed_demo_data
                seed_demo_data(db)
                logger.info("Demo data seeding completed on startup.")
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Startup database initialization: %s", exc)

    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=f"{APP_NAME} API",
        version=VERSION,
        description="Evidence-led project handover platform for engineering teams.",
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )

    setup_middleware(app)
    setup_exception_handlers(app)
    app.include_router(api_router)

    # ── Health & Readiness ────────────────────────────────────

    @app.get("/health", tags=["System"])
    def health():
        """Basic liveness check."""
        return {"status": "ok", "version": VERSION, "app": APP_NAME}

    @app.get("/ready", tags=["System"])
    def readiness():
        """Readiness check — verifies database connectivity."""
        try:
            db = SessionLocal()
            db.execute(text("SELECT 1"))
            db.close()
            return {"status": "ready", "database": "connected"}
        except Exception as exc:
            return {"status": "not_ready", "database": str(exc)}

    return app


app = create_app()
