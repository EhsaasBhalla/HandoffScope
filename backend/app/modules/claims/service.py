"""Claim service operations re-exported for claims module scope."""

from app.modules.evidence.service import review_claim

__all__ = ["review_claim"]
