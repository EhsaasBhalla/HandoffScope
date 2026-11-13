"""All domain enums for HandoffScope.

Each enum uses str+Enum so values serialise cleanly to JSON and
can be stored as PostgreSQL native ENUMs or VARCHAR check-constrained columns.
"""

import enum


# ── Identity & Tenancy ────────────────────────────────────────


class WorkspaceRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class ProjectRole(str, enum.Enum):
    LEAD = "LEAD"
    CONTRIBUTOR = "CONTRIBUTOR"
    REVIEWER = "REVIEWER"


class CaseParticipantRole(str, enum.Enum):
    INITIATOR = "INITIATOR"
    DEPARTING = "DEPARTING"
    REVIEWER = "REVIEWER"
    RECIPIENT = "RECIPIENT"
    CONTRIBUTOR = "CONTRIBUTOR"
    AUDITOR = "AUDITOR"


# ── Handover Case ─────────────────────────────────────────────


class TransitionType(str, enum.Enum):
    PLANNED_DEPARTURE = "PLANNED_DEPARTURE"
    UNEXPECTED_UNAVAILABLE = "UNEXPECTED_UNAVAILABLE"
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"


class CaseStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CONNECTING = "CONNECTING"
    INGESTING = "INGESTING"
    RECONSTRUCTING = "RECONSTRUCTING"
    NEEDS_INPUT = "NEEDS_INPUT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    SHARED = "SHARED"
    PARTIALLY_ACKNOWLEDGED = "PARTIALLY_ACKNOWLEDGED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    TRANSFERRED = "TRANSFERRED"
    CANCELLED = "CANCELLED"


class CaseSyncStatus(str, enum.Enum):
    CURRENT = "CURRENT"
    POTENTIALLY_STALE = "POTENTIALLY_STALE"
    CHANGED_SINCE_APPROVAL = "CHANGED_SINCE_APPROVAL"
    UNKNOWN_FRESHNESS = "UNKNOWN_FRESHNESS"


# ── Sources & Ingestion ──────────────────────────────────────


class SourceType(str, enum.Enum):
    GITHUB_REPO = "GITHUB_REPO"
    GITLAB_REPO = "GITLAB_REPO"
    JIRA_PROJECT = "JIRA_PROJECT"
    LINEAR_TEAM = "LINEAR_TEAM"
    DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"


class SourceRecordType(str, enum.Enum):
    ISSUE = "ISSUE"
    PR = "PR"
    COMMIT = "COMMIT"
    REVIEW = "REVIEW"
    COMMENT = "COMMENT"
    DOCUMENT_SECTION = "DOCUMENT_SECTION"


class ConnectionStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ERROR = "ERROR"
    DISCONNECTED = "DISCONNECTED"
    REVOKED = "REVOKED"


class Sensitivity(str, enum.Enum):
    GENERAL = "GENERAL"
    INTERNAL = "INTERNAL"
    RESTRICTED = "RESTRICTED"


class ProcessingStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class IdentityConfidence(str, enum.Enum):
    VERIFIED = "VERIFIED"
    SUGGESTED = "SUGGESTED"
    UNMATCHED = "UNMATCHED"


class SyncRunStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# ── Jobs ──────────────────────────────────────────────────────


class JobType(str, enum.Enum):
    SOURCE_IMPORT = "SOURCE_IMPORT"
    DOCUMENT_PARSE = "DOCUMENT_PARSE"
    RECONSTRUCTION = "RECONSTRUCTION"
    TRANSFER_PACK_GENERATION = "TRANSFER_PACK_GENERATION"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"


# ── Transfer Packs ────────────────────────────────────────────


class TransferPackStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    NEEDS_INPUT = "NEEDS_INPUT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    SHARED = "SHARED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    ACCEPTED = "ACCEPTED"
    STALE = "STALE"


# ── Claims & Evidence ────────────────────────────────────────


class ClaimType(str, enum.Enum):
    WORK_ITEM = "WORK_ITEM"
    DECISION = "DECISION"
    DEPENDENCY = "DEPENDENCY"
    RISK = "RISK"
    OPERATIONAL_NOTE = "OPERATIONAL_NOTE"
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    NEXT_ACTION = "NEXT_ACTION"


class EvidenceState(str, enum.Enum):
    SUPPORTED = "SUPPORTED"
    INFERRED = "INFERRED"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


class Freshness(str, enum.Enum):
    CURRENT = "CURRENT"
    POTENTIALLY_STALE = "POTENTIALLY_STALE"
    CHANGED_SINCE_APPROVAL = "CHANGED_SINCE_APPROVAL"
    UNKNOWN_FRESHNESS = "UNKNOWN_FRESHNESS"


class ReviewState(str, enum.Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    EDITED_AND_ACCEPTED = "EDITED_AND_ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class EvidenceType(str, enum.Enum):
    DIRECT_REFERENCE = "DIRECT_REFERENCE"
    CONTEXTUAL = "CONTEXTUAL"
    INFERRED_LINK = "INFERRED_LINK"


class ExtractionRunStatus(str, enum.Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class Priority(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ── Questions ─────────────────────────────────────────────────


class QuestionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    PENDING_REVIEW = "PENDING_REVIEW"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
    CANCELLED = "CANCELLED"


class QuestionResponseReviewState(str, enum.Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    AMENDED = "AMENDED"
    REJECTED = "REJECTED"


# ── Responsibility ────────────────────────────────────────────


class ResponsibilityAcceptanceStatus(str, enum.Enum):
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"
