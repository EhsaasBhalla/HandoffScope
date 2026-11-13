import { useState, useEffect, memo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CheckSquare,
  Lightbulb,
  Link2,
  AlertTriangle,
  BookOpen,
  HelpCircle,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  FileCheck2,
  FolderInput,
  Edit2,
  Check,
  X,
  CheckCircle2,
  XCircle,
  RotateCcw,
  History,
} from 'lucide-react';
import { evidenceApi } from '../../api/evidence.api';
import { EvidenceStateBadge } from '../evidence-state-badge/evidence-state-badge';
import { FreshnessBadge } from '../freshness-badge/freshness-badge';
import { ReviewStateBadge } from '../review-state-badge/review-state-badge';
import { EvidenceCard } from '../evidence-card/evidence-card';
import styles from './claim-card.module.css';

function ClaimCardComponent({
  claim,
  availablePacks = [],
  onMoveClaim,
  onUpdateClaim,
  enableReview = false,
  onReviewClaim,
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isMoving, setIsMoving] = useState(false);
  const [isMovingPack, setIsMovingPack] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isReviewing, setIsReviewing] = useState(false);
  const [actionError, setActionError] = useState(null);

  const [editTitle, setEditTitle] = useState(claim?.title || '');
  const [editBody, setEditBody] = useState(claim?.body_text || '');
  const [editPriority, setEditPriority] = useState(claim?.priority || 'MEDIUM');

  // Review action modal/input state
  const [reviewMode, setReviewMode] = useState(null); // 'reject' | 'clarify' | 'edit_and_accept'
  const [reviewReason, setReviewReason] = useState('');
  const [reviewEditedBody, setReviewEditedBody] = useState(claim?.body_text || '');
  const [showOriginal, setShowOriginal] = useState(false);

  // Sync edit form state when claim prop changes
  useEffect(() => {
    if (!claim) return;
    setEditTitle(claim.title || '');
    setEditBody(claim.body_text || '');
    setEditPriority(claim.priority || 'MEDIUM');
    setReviewEditedBody(claim.body_text || '');
    setActionError(null);
  }, [claim?.id, claim?.title, claim?.body_text, claim?.priority]);

  // Fetch full evidence items if expanded
  const { data: claimDetail, isLoading: evidenceLoading } = useQuery({
    queryKey: ['claim-detail', claim?.id],
    queryFn: () => (claim?.id ? evidenceApi.getClaim(claim.id) : null),
    enabled: Boolean(isExpanded && claim?.id),
  });

  if (!claim) return null;

  const renderTypeIcon = (type) => {
    switch ((type || '').toUpperCase()) {
      case 'WORK_ITEM':
        return <CheckSquare size={16} />;
      case 'DECISION':
        return <Lightbulb size={16} />;
      case 'DEPENDENCY':
        return <Link2 size={16} />;
      case 'RISK':
        return <AlertTriangle size={16} />;
      case 'OPERATIONAL_NOTE':
        return <BookOpen size={16} />;
      case 'KNOWLEDGE_GAP':
        return <HelpCircle size={16} />;
      case 'NEXT_ACTION':
        return <ArrowRight size={16} />;
      default:
        return <FileCheck2 size={16} />;
    }
  };

  const handleSaveEdit = async (e) => {
    if (e) e.stopPropagation();
    if (!onUpdateClaim || isSaving) return;
    if (!editTitle.trim()) {
      setActionError('Title cannot be empty.');
      return;
    }
    setActionError(null);
    setIsSaving(true);
    try {
      await onUpdateClaim(claim.id, {
        title: editTitle.trim(),
        body_text: editBody.trim(),
        priority: editPriority,
      });
      setIsEditing(false);
    } catch (err) {
      setActionError(err?.data?.detail || err?.message || 'Failed to update claim');
    } finally {
      setIsSaving(false);
    }
  };

  const handleMoveSelect = async (e) => {
    e.stopPropagation();
    const targetPackId = e.target.value;
    if (targetPackId && onMoveClaim && !isMovingPack) {
      setActionError(null);
      setIsMovingPack(true);
      try {
        await onMoveClaim(claim.id, targetPackId);
        setIsMoving(false);
      } catch (err) {
        setActionError(err?.data?.detail || err?.message || 'Failed to move claim');
      } finally {
        setIsMovingPack(false);
      }
    } else {
      setIsMoving(false);
    }
  };

  const handleExecuteReview = async (action, e) => {
    if (e) e.stopPropagation();
    if (!onReviewClaim || isReviewing) return;
    setActionError(null);
    try {
      if (action === 'accept') {
        setIsReviewing(true);
        await onReviewClaim(claim.id, { action: 'accept' });
      } else if (action === 'resubmit') {
        setIsReviewing(true);
        await onReviewClaim(claim.id, { action: 'resubmit' });
      } else if (action === 'reject') {
        if (!reviewReason.trim()) {
          setActionError('A reason is required to reject a claim.');
          return;
        }
        setIsReviewing(true);
        await onReviewClaim(claim.id, { action: 'reject', reason: reviewReason.trim() });
        setReviewMode(null);
        setReviewReason('');
      } else if (action === 'needs_clarification') {
        if (!reviewReason.trim()) {
          setActionError('Clarification details are required.');
          return;
        }
        setIsReviewing(true);
        await onReviewClaim(claim.id, { action: 'needs_clarification', reason: reviewReason.trim() });
        setReviewMode(null);
        setReviewReason('');
      } else if (action === 'edit_and_accept') {
        if (!reviewEditedBody.trim()) {
          setActionError('Edited body text cannot be empty.');
          return;
        }
        setIsReviewing(true);
        await onReviewClaim(claim.id, {
          action: 'edit_and_accept',
          edited_body: reviewEditedBody.trim(),
          reason: reviewReason.trim() || undefined,
        });
        setReviewMode(null);
        setReviewReason('');
      }
    } catch (err) {
      setActionError(err?.data?.detail || err?.message || 'Review action failed');
    } finally {
      setIsReviewing(false);
    }
  };

  const evidenceItems = claimDetail?.evidence || [];
  const evCount = claim.evidence_count ?? evidenceItems.length;
  const targetPacks = (availablePacks || []).filter((p) => p && p.id !== claim.transfer_pack_id);

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <div className={styles.typeMeta}>
          <div className={styles.typeIconWrap}>
            {renderTypeIcon(claim.claim_type)}
          </div>
          <span className={styles.typeLabel}>{(claim.claim_type || '').replaceAll('_', ' ')}</span>
        </div>

        <div className={styles.badgesRow}>
          {claim.priority && (claim.priority === 'HIGH' || claim.priority === 'CRITICAL') && (
            <span className={styles.priorityBadge}>{claim.priority}</span>
          )}
          <EvidenceStateBadge state={claim.evidence_state} />
          <FreshnessBadge freshness={claim.freshness} />
          <ReviewStateBadge state={claim.review_state} />

          {/* Action buttons */}
          <div className={styles.actionsGroup}>
            {targetPacks.length > 0 && onMoveClaim && (
              isMoving ? (
                <select
                  className={styles.moveSelect}
                  onChange={handleMoveSelect}
                  defaultValue=""
                  autoFocus
                  disabled={isMovingPack}
                  onBlur={() => {
                    if (!isMovingPack) setIsMoving(false);
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <option value="" disabled>
                    {isMovingPack ? 'Moving claim…' : 'Move to Pack...'}
                  </option>
                  {targetPacks.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              ) : (
                <button
                  type="button"
                  className={styles.actionBtn}
                  onClick={(e) => {
                    e.stopPropagation();
                    setIsMoving(true);
                  }}
                  title="Move claim to another Transfer Pack"
                >
                  <FolderInput size={12} /> Move
                </button>
              )
            )}

            {onUpdateClaim && !isEditing && (
              <button
                type="button"
                className={styles.actionBtn}
                onClick={(e) => {
                  e.stopPropagation();
                  setIsEditing(true);
                }}
                title="Edit claim details"
              >
                <Edit2 size={12} /> Edit
              </button>
            )}
          </div>
        </div>
      </div>

      {actionError && (
        <div className={styles.actionError} onClick={(e) => e.stopPropagation()}>
          {actionError}
        </div>
      )}

      {isEditing ? (
        <div
          style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="text"
            value={editTitle}
            disabled={isSaving}
            onChange={(e) => setEditTitle(e.target.value)}
            style={{
              padding: '6px 8px',
              backgroundColor: 'var(--color-bg-primary)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--color-text-primary)',
              fontSize: '13px',
              fontWeight: 600,
            }}
          />
          <textarea
            rows={3}
            value={editBody}
            disabled={isSaving}
            onChange={(e) => setEditBody(e.target.value)}
            style={{
              padding: '6px 8px',
              backgroundColor: 'var(--color-bg-primary)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--color-text-primary)',
              fontSize: '12px',
            }}
          />
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', justifyContent: 'flex-end' }}>
            <select
              value={editPriority}
              disabled={isSaving}
              onChange={(e) => setEditPriority(e.target.value)}
              className={styles.moveSelect}
            >
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </select>
            <button
              type="button"
              className={styles.actionBtn}
              disabled={isSaving}
              onClick={(e) => {
                e.stopPropagation();
                setIsEditing(false);
                setActionError(null);
              }}
            >
              <X size={12} /> Cancel
            </button>
            <button
              type="button"
              className={styles.actionBtn}
              style={{ backgroundColor: 'var(--color-accent)', color: 'var(--color-text-inverse)' }}
              disabled={isSaving}
              onClick={handleSaveEdit}
            >
              <Check size={12} /> {isSaving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      ) : (
        <>
          <h4 className={styles.title}>{claim.title}</h4>
          {claim.body_text && <p className={styles.body}>{claim.body_text}</p>}

          {/* Historical / Original Body if edited */}
          {claim.original_body_text && (
            <div style={{ marginTop: '4px' }}>
              <button
                type="button"
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--color-accent)',
                  fontSize: '11px',
                  cursor: 'pointer',
                  padding: 0,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  setShowOriginal(!showOriginal);
                }}
              >
                <History size={11} /> {showOriginal ? 'Hide Original Text' : 'View Original Pre-Edit Text'}
              </button>
              {showOriginal && (
                <div className={styles.originalBodyBox} style={{ marginTop: '4px' }}>
                  <strong>Original:</strong> {claim.original_body_text}
                </div>
              )}
            </div>
          )}

          {/* Review Notes / Rejection Reason Callout */}
          {claim.review_notes && (
            <div className={styles.notesBox}>
              <strong>Review Notes:</strong> {claim.review_notes}
            </div>
          )}
        </>
      )}

      {/* Review Actions Toolbar */}
      {(enableReview || onReviewClaim) && (
        <div className={styles.reviewToolbar} onClick={(e) => e.stopPropagation()}>
          <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-muted)' }}>
            Review:
          </span>

          {reviewMode ? (
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '8px', padding: '8px 0' }}>
              {reviewMode === 'edit_and_accept' && (
                <textarea
                  rows={3}
                  disabled={isReviewing}
                  value={reviewEditedBody}
                  onChange={(e) => setReviewEditedBody(e.target.value)}
                  placeholder="Edit claim body text..."
                  style={{
                    padding: '8px',
                    backgroundColor: 'var(--color-bg-primary)',
                    border: '1px solid var(--color-border)',
                    borderRadius: '4px',
                    color: 'var(--color-text-primary)',
                    fontSize: '12px',
                  }}
                />
              )}
              <input
                type="text"
                disabled={isReviewing}
                value={reviewReason}
                onChange={(e) => setReviewReason(e.target.value)}
                placeholder={
                  reviewMode === 'reject'
                    ? 'Enter reason for rejection (required)...'
                    : reviewMode === 'clarify'
                    ? 'What clarification is required? (spawns question)...'
                    : 'Reason or notes for edits (optional)...'
                }
                style={{
                  padding: '6px 8px',
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: '4px',
                  color: 'var(--color-text-primary)',
                  fontSize: '12px',
                }}
              />
              <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className={styles.actionBtn}
                  disabled={isReviewing}
                  onClick={(e) => {
                    e.stopPropagation();
                    setReviewMode(null);
                    setReviewReason('');
                    setActionError(null);
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={isReviewing}
                  className={`${styles.actionBtn} ${
                    reviewMode === 'reject'
                      ? styles.reviewBtnReject
                      : reviewMode === 'clarify'
                      ? styles.reviewBtnClarify
                      : styles.reviewBtnAccept
                  }`}
                  onClick={(e) => handleExecuteReview(reviewMode === 'clarify' ? 'needs_clarification' : reviewMode, e)}
                >
                  <Check size={12} /> {isReviewing ? 'Saving…' : `Confirm ${reviewMode.replaceAll('_', ' ')}`}
                </button>
              </div>
            </div>
          ) : (
            <>
              {claim.review_state !== 'ACCEPTED' && (
                <button
                  type="button"
                  disabled={isReviewing}
                  className={`${styles.actionBtn} ${styles.reviewBtnAccept}`}
                  onClick={(e) => handleExecuteReview('accept', e)}
                  title="Accept claim as-is"
                >
                  <CheckCircle2 size={12} /> Accept
                </button>
              )}

              <button
                type="button"
                disabled={isReviewing}
                className={`${styles.actionBtn} ${styles.reviewBtnAccept}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setReviewMode('edit_and_accept');
                  setReviewEditedBody(claim.body_text || '');
                  setActionError(null);
                }}
                title="Modify body and accept claim"
              >
                <Edit2 size={12} /> Edit & Accept
              </button>

              {claim.review_state !== 'REJECTED' && (
                <button
                  type="button"
                  disabled={isReviewing}
                  className={`${styles.actionBtn} ${styles.reviewBtnReject}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setReviewMode('reject');
                    setActionError(null);
                  }}
                  title="Reject claim with reason"
                >
                  <XCircle size={12} /> Reject
                </button>
              )}

              {claim.review_state !== 'NEEDS_CLARIFICATION' && (
                <button
                  type="button"
                  disabled={isReviewing}
                  className={`${styles.actionBtn} ${styles.reviewBtnClarify}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setReviewMode('clarify');
                    setActionError(null);
                  }}
                  title="Request clarification (creates question)"
                >
                  <HelpCircle size={12} /> Clarify
                </button>
              )}

              {(claim.review_state === 'REJECTED' || claim.review_state === 'NEEDS_CLARIFICATION') && (
                <button
                  type="button"
                  disabled={isReviewing}
                  className={styles.actionBtn}
                  onClick={(e) => handleExecuteReview('resubmit', e)}
                  title="Resubmit for review"
                >
                  <RotateCcw size={12} /> Resubmit
                </button>
              )}
            </>
          )}
        </div>
      )}

      <div className={styles.footer}>
        <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
          {evCount} grounded evidence reference{evCount === 1 ? '' : 's'}
        </span>

        <button
          type="button"
          className={styles.expandBtn}
          onClick={(e) => {
            e.stopPropagation();
            setIsExpanded((prev) => !prev);
          }}
        >
          {isExpanded ? (
            <>
              Hide Evidence <ChevronUp size={14} />
            </>
          ) : (
            <>
              Inspect Evidence <ChevronDown size={14} />
            </>
          )}
        </button>
      </div>

      {isExpanded && (
        <div className={styles.evidenceDrawer} onClick={(e) => e.stopPropagation()}>
          <h5 className={styles.drawerTitle}>Grounded Source Citations</h5>
          {evidenceLoading ? (
            <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', padding: '0.5rem 0' }}>
              Loading evidence records...
            </div>
          ) : evidenceItems.length === 0 ? (
            <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
              No explicit source citations attached to this claim.
            </div>
          ) : (
            evidenceItems.map((ev) => <EvidenceCard key={ev.id} evidence={ev} />)
          )}
        </div>
      )}
    </div>
  );
}

export const ClaimCard = memo(ClaimCardComponent);
export default ClaimCard;
