"""Unit tests for handover case state machine transitions."""

import pytest
from app.db.enums import CaseStatus
from app.modules.handover_cases.service import can_transition, VALID_TRANSITIONS


def test_valid_forward_transitions():
    assert can_transition(CaseStatus.DRAFT, CaseStatus.CONNECTING) is True
    assert can_transition(CaseStatus.CONNECTING, CaseStatus.INGESTING) is True
    assert can_transition(CaseStatus.INGESTING, CaseStatus.RECONSTRUCTING) is True
    assert can_transition(CaseStatus.RECONSTRUCTING, CaseStatus.UNDER_REVIEW) is True
    assert can_transition(CaseStatus.UNDER_REVIEW, CaseStatus.APPROVED) is True
    assert can_transition(CaseStatus.APPROVED, CaseStatus.SHARED) is True
    assert can_transition(CaseStatus.SHARED, CaseStatus.ACKNOWLEDGED) is True
    assert can_transition(CaseStatus.ACKNOWLEDGED, CaseStatus.TRANSFERRED) is True


def test_invalid_backward_transitions():
    # Cannot jump backward from UNDER_REVIEW to DRAFT directly
    assert can_transition(CaseStatus.UNDER_REVIEW, CaseStatus.DRAFT) is False
    # Cannot jump from DRAFT to APPROVED directly
    assert can_transition(CaseStatus.DRAFT, CaseStatus.APPROVED) is False
    # Terminal state cannot transition to anything
    assert can_transition(CaseStatus.TRANSFERRED, CaseStatus.DRAFT) is False
    assert can_transition(CaseStatus.CANCELLED, CaseStatus.DRAFT) is False


def test_cancellation_allowed_from_early_stages():
    assert can_transition(CaseStatus.DRAFT, CaseStatus.CANCELLED) is True
    assert can_transition(CaseStatus.CONNECTING, CaseStatus.CANCELLED) is True
    assert can_transition(CaseStatus.INGESTING, CaseStatus.CANCELLED) is True
    assert can_transition(CaseStatus.RECONSTRUCTING, CaseStatus.CANCELLED) is True
