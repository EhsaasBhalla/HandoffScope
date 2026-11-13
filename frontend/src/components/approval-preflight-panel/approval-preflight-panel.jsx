import { useState, useEffect } from 'react';
import { AlertTriangle, CheckCircle2, ShieldAlert, ShieldCheck, X, Loader2 } from 'lucide-react';
import { usePermissions } from '../../hooks/usePermissions';

export function ApprovalPreflightPanel({
  queueSummary,
  onApproveVersion,
  isSubmitting = false,
  styles = {},
}) {
  const { hasCapability } = usePermissions();
  const [modalMode, setModalMode] = useState(null); // null | 'normal' | 'override'
  const [amendmentReason, setAmendmentReason] = useState('');
  const [overrideReason, setOverrideReason] = useState('');
  const [submitError, setSubmitError] = useState(null);

  useEffect(() => {
    if (!modalMode) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && !isSubmitting) {
        handleClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [modalMode, isSubmitting]);

  if (!queueSummary) return null;

  const blockers = Array.isArray(queueSummary.blockers) ? queueSummary.blockers : [];
  const criticalBlockers = blockers.filter(
    (b) => typeof b === 'object' && b !== null && (b.severity === 'critical' || !b.overridable)
  );
  const nonCriticalBlockers = blockers.filter(
    (b) => typeof b === 'object' && b !== null && b.severity !== 'critical' && b.overridable
  );
  const canUserApprove = hasCapability('case.approve') || hasCapability('review.submit');
  const canLeadOverride =
    !queueSummary.can_approve &&
    !queueSummary.has_critical_blockers &&
    queueSummary.can_override &&
    hasCapability('case.approve_override');

  const handleClose = () => {
    if (isSubmitting) return;
    setModalMode(null);
    setOverrideReason('');
    setSubmitError(null);
  };

  const handleConfirm = async () => {
    if (isSubmitting) return;
    const isOverride = modalMode === 'override';
    if (isOverride && overrideReason.trim().length < 10) {
      return;
    }
    setSubmitError(null);
    try {
      if (onApproveVersion) {
        await onApproveVersion({
          amendment_reason: amendmentReason.trim() || undefined,
          override_blockers: isOverride,
          override_reason: isOverride ? overrideReason.trim() : undefined,
        });
      }
      setModalMode(null);
      setAmendmentReason('');
      setOverrideReason('');
    } catch (err) {
      setSubmitError(
        err?.response?.data?.detail ||
          err?.data?.detail ||
          err?.message ||
          'Failed to approve version snapshot.'
      );
    }
  };

  return (
    <>
      <div
        className={`${styles.readinessBanner || ''} ${
          queueSummary.can_approve ? (styles.readinessReady || '') : (styles.readinessBlocked || '')
        }`}
      >
        <div className={styles.readinessInfo || ''}>
          {queueSummary.can_approve ? (
            <CheckCircle2 size={24} className={styles.readinessIconReady} style={{ color: 'var(--color-success)', flexShrink: 0 }} />
          ) : queueSummary.has_critical_blockers ? (
            <ShieldAlert size={24} style={{ color: 'var(--color-error)', flexShrink: 0 }} />
          ) : (
            <AlertTriangle size={24} className={styles.readinessIconBlocked} style={{ color: 'var(--color-warning)', flexShrink: 0 }} />
          )}

          <div style={{ flex: 1 }}>
            <div className={styles.readinessTitle || ''}>
              {queueSummary.can_approve
                ? 'All Review Preconditions Satisfied'
                : queueSummary.has_critical_blockers
                ? 'Critical Blockers — Approval Blocked'
                : 'Non-Critical Blockers Pending'}
            </div>

            {queueSummary.can_approve ? (
              <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                All transfer packs, claims, and handover questions are resolved. Ready to freeze version v
                {(queueSummary.current_version_number || 0) + 1}.
              </p>
            ) : blockers.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '6px' }}>
                {criticalBlockers.length > 0 && (
                  <div>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--color-error)', textTransform: 'uppercase', marginBottom: '2px' }}>
                      Critical Blockers (Cannot Be Overridden)
                    </div>
                    <ul className={styles.blockingList || ''}>
                      {criticalBlockers.map((b, idx) => (
                        <li key={idx} style={{ color: 'var(--color-error)' }}>
                          {b.message || b.reason || (typeof b === 'string' ? b : 'Critical blocker')}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {nonCriticalBlockers.length > 0 && (
                  <div>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--color-warning)', textTransform: 'uppercase', marginBottom: '2px' }}>
                      Non-Critical Blockers (Lead Override Eligible)
                    </div>
                    <ul className={styles.blockingList || ''}>
                      {nonCriticalBlockers.map((b, idx) => (
                        <li key={idx}>
                          {b.message || b.reason || (typeof b === 'string' ? b : 'Blocker')}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <ul className={styles.blockingList || ''}>
                {(queueSummary.blocking_reasons || []).map((reason, idx) => (
                  <li key={idx}>{reason}</li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            type="button"
            className={styles.approveBtn || ''}
            onClick={() => setModalMode('normal')}
            disabled={!queueSummary.can_approve || !canUserApprove || isSubmitting}
            title={
              !canUserApprove
                ? 'Reviewer or Lead permission required to approve'
                : !queueSummary.can_approve
                ? 'Resolve all blockers before ordinary approval'
                : 'Approve and seal immutable version snapshot'
            }
          >
            <ShieldCheck size={16} />
            Approve &amp; Seal Version
          </button>

          {canLeadOverride && (
            <button
              type="button"
              className={styles.approveBtn || ''}
              style={{
                backgroundColor: 'var(--color-warning)',
                color: 'var(--color-text-inverse)',
                borderColor: 'var(--color-warning)',
              }}
              onClick={() => setModalMode('override')}
              disabled={isSubmitting}
              title="Designated Lead/Owner override for non-critical blockers with audit justification"
            >
              <AlertTriangle size={16} />
              Approve with Override
            </button>
          )}
        </div>
      </div>

      {modalMode && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '16px',
          }}
          onClick={handleClose}
          role="dialog"
          aria-modal="true"
          aria-labelledby="approval-preflight-modal-title"
        >
          <div
            style={{
              backgroundColor: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-lg)',
              padding: '20px',
              maxWidth: '520px',
              width: '100%',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 id="approval-preflight-modal-title" style={{ margin: 0, fontSize: '16px' }}>
                {modalMode === 'override'
                  ? 'Approve with Lead Override (Audited)'
                  : 'Approve & Freeze Version Snapshot'}
              </h3>
              <button
                type="button"
                onClick={handleClose}
                disabled={isSubmitting}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--color-text-muted)',
                  cursor: isSubmitting ? 'not-allowed' : 'pointer',
                  opacity: isSubmitting ? 0.5 : 1,
                }}
                aria-label="Close modal"
              >
                <X size={18} />
              </button>
            </div>

            {submitError && (
              <div
                style={{
                  padding: '8px 12px',
                  borderRadius: '6px',
                  backgroundColor: 'var(--color-error-bg, rgba(239, 68, 68, 0.1))',
                  border: '1px solid var(--color-error, #ef4444)',
                  color: 'var(--color-error, #ef4444)',
                  fontSize: '12px',
                }}
              >
                {submitError}
              </div>
            )}

            {modalMode === 'override' ? (
              <div
                style={{
                  padding: '10px 12px',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(245, 158, 11, 0.1)',
                  border: '1px solid rgba(245, 158, 11, 0.35)',
                  fontSize: '12px',
                  color: 'var(--color-text-primary)',
                }}
              >
                <strong>Overriding {nonCriticalBlockers.length} non-critical blocker(s):</strong>
                <ul style={{ margin: '6px 0 0', paddingLeft: '18px' }}>
                  {nonCriticalBlockers.map((b, i) => (
                    <li key={i}>{b.message || b.reason || (typeof b === 'string' ? b : 'Blocker')}</li>
                  ))}
                </ul>
                <p style={{ margin: '6px 0 0', color: 'var(--color-text-muted)' }}>
                  Overridden questions stay open and are preserved inside the approved snapshot with your justification.
                </p>
              </div>
            ) : (
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', margin: 0 }}>
                Approving creates an immutable snapshot of all Transfer Packs, verified claims, and evidence citations.
              </p>
            )}

            {modalMode === 'override' && (
              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                  Override Justification (Required, min 10 characters)
                </label>
                <textarea
                  rows={3}
                  required
                  disabled={isSubmitting}
                  placeholder="Explain why these non-critical open items are acceptable to defer post-handover..."
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px',
                    backgroundColor: 'var(--color-bg-primary)',
                    border: '1px solid var(--color-border)',
                    borderRadius: '6px',
                    color: 'var(--color-text-primary)',
                    fontSize: '13px',
                  }}
                />
                {overrideReason.trim().length > 0 && overrideReason.trim().length < 10 && (
                  <span style={{ fontSize: '11px', color: 'var(--color-error)' }}>
                    Please provide at least 10 characters of justification.
                  </span>
                )}
              </div>
            )}

            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px', color: 'var(--color-text-secondary)' }}>
                Amendment / Approval Notes (Optional)
              </label>
              <textarea
                rows={2}
                disabled={isSubmitting}
                placeholder="e.g. Verified primary packs and runbooks."
                value={amendmentReason}
                onChange={(e) => setAmendmentReason(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px',
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: '6px',
                  color: 'var(--color-text-primary)',
                  fontSize: '13px',
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={handleClose}
                disabled={isSubmitting}
                style={{
                  padding: '7px 14px',
                  background: 'transparent',
                  border: '1px solid var(--color-border)',
                  borderRadius: '6px',
                  color: 'var(--color-text-secondary)',
                  cursor: isSubmitting ? 'not-allowed' : 'pointer',
                  opacity: isSubmitting ? 0.5 : 1,
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.approveBtn || ''}
                disabled={
                  isSubmitting ||
                  (modalMode === 'override' && overrideReason.trim().length < 10)
                }
                onClick={handleConfirm}
                style={
                  modalMode === 'override'
                    ? { backgroundColor: 'var(--color-warning)', color: 'var(--color-text-inverse)' }
                    : undefined
                }
              >
                {isSubmitting ? (
                  <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} />
                ) : (
                  <ShieldCheck size={15} />
                )}
                {isSubmitting
                  ? 'Freezing Snapshot…'
                  : modalMode === 'override'
                  ? 'Confirm Override & Freeze'
                  : 'Confirm & Freeze Version'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
