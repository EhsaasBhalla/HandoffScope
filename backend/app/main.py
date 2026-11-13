"""HandoffScope FastAPI application factory and entry point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text

from app.api.router import router as api_router
from app.core.constants import APP_NAME, VERSION
from app.core.exceptions import setup_exception_handlers
from app.core.logging import logger
from app.core.middleware import setup_middleware
from app.db.base import SessionLocal, engine
from app.db.schema_guard import ensure_additive_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager: sets up DB tables and seeds on first launch."""
    try:
        ensure_additive_schema(engine)

        db = SessionLocal()
        try:
            from app.modules.workspaces.models import User
            if db.query(User).count() == 0:
                logger.info("Fresh database detected — seeding demo data and synthetic fixture...")
                from app.seed.demo_seed import seed_demo_data
                seed_demo_data(db)
                logger.info("Demo data seeding completed on startup.")
            else:
                from app.seed.repo_fixtures import seed_project_repo_fixtures
                seed_project_repo_fixtures(db)
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

    # ── Health, Root & Readiness (Supports both GET and HEAD for Uptime Bots) ──

    @app.api_route("/", methods=["GET", "HEAD"], tags=["System"])
    def root():
        """Root endpoint returning service status (ideal for uptime bots and monitors)."""
        return {"status": "ok", "app": APP_NAME, "version": VERSION, "message": "HandoffScope API is running"}

    @app.api_route("/health", methods=["GET", "HEAD"], tags=["System"])
    @app.api_route("/api/v1/health", methods=["GET", "HEAD"], tags=["System"])
    def health():
        """Basic liveness check."""
        return {"status": "ok", "version": VERSION, "app": APP_NAME}

    @app.api_route("/ready", methods=["GET", "HEAD"], tags=["System"])
    def readiness():
        """Readiness check — verifies database connectivity."""
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ready", "database": "connected"}
        except Exception as exc:
            return {"status": "not_ready", "database": str(exc)}
        finally:
            db.close()

    return app


app = create_app()
