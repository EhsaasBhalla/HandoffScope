"""API v1 router — includes all domain routers."""

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.workspaces.router import router as workspaces_router
from app.modules.projects.router import router as projects_router
from app.modules.audit.router import router as audit_router
from app.modules.handover_cases.router import router as cases_router
from app.modules.sources.router import router as sources_router
from app.modules.github.router import router as github_router
from app.modules.jobs.router import router as jobs_router
from app.modules.documents.router import router as documents_router
from app.modules.questions.router import router as questions_router

router = APIRouter()

# ── Phase 2: Auth & Users ─────────────────────────────────────
router.include_router(auth_router)
router.include_router(workspaces_router)
router.include_router(projects_router)

# ── Phase 3: Cases & Audit ────────────────────────────────────
router.include_router(cases_router)
router.include_router(audit_router)

# ── Phase 4: Sources & Ingestion ──────────────────────────────
router.include_router(sources_router)
router.include_router(github_router)
router.include_router(jobs_router)
router.include_router(documents_router)

# ── Phase 7: Questions & Answers ──────────────────────────────
router.include_router(questions_router)
