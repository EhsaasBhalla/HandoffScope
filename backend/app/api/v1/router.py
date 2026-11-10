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
from app.modules.identity.router import router as identity_router
from app.modules.timeline.router import router as timeline_router
from app.modules.reconstruction.router import router as reconstruction_router
from app.modules.evidence.router import router as evidence_router
from app.modules.transfer_packs.router import router as transfer_packs_router
from app.modules.questions.router import router as questions_router
from app.modules.reviews.router import router as reviews_router
from app.modules.sharing.router import router as sharing_router
from app.modules.recipients.router import router as recipients_router
from app.modules.dashboard.router import router as dashboard_router

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

# ── Phase 5: Normalisation & Identity ─────────────────────────
router.include_router(identity_router)
router.include_router(timeline_router)

# ── Phase 6: AI Extraction & Evidence ─────────────────────────
router.include_router(reconstruction_router)
router.include_router(evidence_router)
router.include_router(transfer_packs_router)

# ── Phase 7: Questions & Answers ──────────────────────────────
router.include_router(questions_router)

# ── Phase 8: Review & Approval ────────────────────────────────
router.include_router(reviews_router)

# ── Phase 9: Recipient Access & Responsibility Transfer ───────
router.include_router(sharing_router)
router.include_router(recipients_router)

# ── Phase 10: Overview & Hardening ────────────────────────────
router.include_router(dashboard_router)
