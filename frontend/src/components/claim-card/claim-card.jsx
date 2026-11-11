import { useState, useEffect } from 'react';
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

export function ClaimCard({
  claim,
  availablePacks = [],
  onMoveClaim,
  onUpdateClaim,
  enableReview = false,
  onReviewClaim,
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isMoving, setIsMoving] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(claim.title);
  const [editBody, setEditBody] = useState(claim.body_text || '');
  const [editPriority, setEditPriority] = useState(claim.priority || 'MEDIUM');

  // Review action modal/input state
  const [reviewMode, setReviewMode] = useState(null); // 'reject' | 'clarify' | 'edit_and_accept'
  const [reviewReason, setReviewReason] = useState('');
  const [reviewEditedBody, setReviewEditedBody] = useState(claim.body_text || '');
  const [showOriginal, setShowOriginal] = useState(false);

  // Sync edit form state when claim prop changes
  useEffect(() => {
    setEditTitle(claim.title);
    setEditBody(claim.body_text || '');
    setEditPriority(claim.priority || 'MEDIUM');
    setReviewEditedBody(claim.body_text || '');
  }, [claim.id, claim.title, claim.body_text, claim.priority]);

  // Fetch full evidence items if expanded
  const { data: claimDetail, isLoading: evidenceLoading } = useQuery({
    queryKey: ['claim-detail', claim.id],
    queryFn: () => evidenceApi.getClaim(claim.id),
    enabled: isExpanded,
  });

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

  const handleSaveEdit = async () => {
    if (onUpdateClaim) {
      await onUpdateClaim(claim.id, {
        title: editTitle,
        body_text: editBody,
        priority: editPriority,
      });
    }
    setIsEditing(false);
  };

  const handleMoveSelect = async (e) => {
    const targetPackId = e.target.value;
    if (targetPackId && onMoveClaim) {
      await onMoveClaim(claim.id, targetPackId);
    }
    setIsMoving(false);
  };

  const handleExecuteReview = async (action) => {
    if (!onReviewClaim) return;
    try {
      if (action === 'accept') {
        await onReviewClaim(claim.id, { action: 'accept' });
      } else if (action === 'resubmit') {
        await onReviewClaim(claim.id, { action: 'resubmit' });
      } else if (action === 'reject') {
        if (!reviewReason.trim()) {
          alert('A reason is required to reject a claim.');
          return;
        }
        await onReviewClaim(claim.id, { action: 'reject', reason: reviewReason.trim() });
        setReviewMode(null);
        setReviewReason('');
      } else if (action === 'needs_clarification') {
        if (!reviewReason.trim()) {
          alert('Clarification details are required.');
          return;
        }
        await onReviewClaim(claim.id, { action: 'needs_clarification', reason: reviewReason.trim() });
        setReviewMode(null);
        setReviewReason('');
      } else if (action === 'edit_and_accept') {
        if (!reviewEditedBody.trim()) {
          alert('Edited body text cannot be empty.');
          return;
        }
        await onReviewClaim(claim.id, {
          action: 'edit_and_accept',
          edited_body: reviewEditedBody.trim(),
          reason: reviewReason.trim() || undefined,
        });
        setReviewMode(null);
        setReviewReason('');
      }
    } catch (err) {
      alert(err?.data?.detail || err?.message || 'Review action failed');
    }
  };

  const evidenceItems = claimDetail?.evidence || [];
  const evCount = claim.evidence_count ?? evidenceItems.length;
  const targetPacks = availablePacks.filter((p) => p.id !== claim.transfer_pack_id);

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <div className={styles.typeMeta}>
          <div className={styles.typeIconWrap}>
            {renderTypeIcon(claim.claim_type)}
          </div>
          <span className={styles.typeLabel}>{claim.claim_type?.replace('_', ' ')}</span>
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
                  onBlur={() => setIsMoving(false)}
                >
                  <option value="" disabled>Move to Pack...</option>
                  {targetPacks.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              ) : (
                <button
                  className={styles.actionBtn}
                  onClick={() => setIsMoving(true)}
                  title="Move claim to another Transfer Pack"
                >
                  <FolderInput size={12} /> Move
                </button>
              )
            )}

            {onUpdateClaim && !isEditing && (
              <button
                className={styles.actionBtn}
                onClick={() => setIsEditing(true)}
                title="Edit claim details"
              >
                <Edit2 size={12} /> Edit
              </button>
            )}
          </div>
        </div>
      </div>

      {isEditing ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <input
            type="text"
            value={editTitle}
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
              onChange={(e) => setEditPriority(e.target.value)}
              className={styles.moveSelect}
            >
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </select>
            <button
              className={styles.actionBtn}
              onClick={() => setIsEditing(false)}
            >
              <X size={12} /> Cancel
            </button>
            <button
              className={styles.actionBtn}
              style={{ backgroundColor: 'var(--color-accent)', color: 'var(--color-text-inverse)' }}
              onClick={handleSaveEdit}
            >
              <Check size={12} /> Save
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
                onClick={() => setShowOriginal(!showOriginal)}
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
        <div className={styles.reviewToolbar}>
          <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-muted)' }}>
            Review:
          </span>

          {reviewMode ? (
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '8px', padding: '8px 0' }}>
              {reviewMode === 'edit_and_accept' && (
                <textarea
                  rows={3}
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
                <button className={styles.actionBtn} onClick={() => { setReviewMode(null); setReviewReason(''); }}>
                  Cancel
                </button>
                <button
                  className={`${styles.actionBtn} ${
                    reviewMode === 'reject'
                      ? styles.reviewBtnReject
                      : reviewMode === 'clarify'
                      ? styles.reviewBtnClarify
                      : styles.reviewBtnAccept
                  }`}
                  onClick={() => handleExecuteReview(reviewMode === 'clarify' ? 'needs_clarification' : reviewMode)}
                >
                  <Check size={12} /> Confirm {reviewMode.replace('_', ' ')}
                </button>
              </div>
            </div>
          ) : (
            <>
              {claim.review_state !== 'ACCEPTED' && (
                <button
                  className={`${styles.actionBtn} ${styles.reviewBtnAccept}`}
                  onClick={() => handleExecuteReview('accept')}
                  title="Accept claim as-is"
                >
                  <CheckCircle2 size={12} /> Accept
                </button>
              )}

              <button
                className={`${styles.actionBtn} ${styles.reviewBtnAccept}`}
                onClick={() => {
                  setReviewMode('edit_and_accept');
                  setReviewEditedBody(claim.body_text || '');
                }}
                title="Modify body and accept claim"
              >
                <Edit2 size={12} /> Edit & Accept
              </button>

              {claim.review_state !== 'REJECTED' && (
                <button
                  className={`${styles.actionBtn} ${styles.reviewBtnReject}`}
                  onClick={() => setReviewMode('reject')}
                  title="Reject claim with reason"
                >
                  <XCircle size={12} /> Reject
                </button>
              )}

              {claim.review_state !== 'NEEDS_CLARIFICATION' && (
                <button
                  className={`${styles.actionBtn} ${styles.reviewBtnClarify}`}
                  onClick={() => setReviewMode('clarify')}
                  title="Request clarification (creates question)"
                >
                  <HelpCircle size={12} /> Clarify
                </button>
              )}

              {(claim.review_state === 'REJECTED' || claim.review_state === 'NEEDS_CLARIFICATION') && (
                <button
                  className={styles.actionBtn}
                  onClick={() => handleExecuteReview('resubmit')}
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
          className={styles.expandBtn}
          onClick={() => setIsExpanded((prev) => !prev)}
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
        <div className={styles.evidenceDrawer}>
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

export default ClaimCard;
