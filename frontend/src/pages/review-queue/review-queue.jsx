import { useState, useMemo, useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, Link } from 'react-router-dom';
import {
  CheckSquare,
  ShieldCheck,
  CheckCircle2,
  Clock,
  HelpCircle,
  XCircle,
  FileCheck2,
  Layers,
  History,
  X,
  Eye,
  Search,
  ArrowRight,
  AlertTriangle,
} from 'lucide-react';
import { httpClient } from '../../api/httpClient';
import { reviewApi } from '../../api/review.api';
import { evidenceApi } from '../../api/evidence.api';
import { transferPackApi } from '../../api/transferPack.api';
import { ClaimCard } from '../../components/claim-card/claim-card';
import { ApprovalPreflightPanel } from '../../components/approval-preflight-panel/approval-preflight-panel';
import styles from './review-queue.module.css';

const REVIEW_STATE_FILTERS = [
  { id: 'ALL', label: 'All Review States' },
  { id: 'PENDING_REVIEW', label: 'Pending Review' },
  { id: 'ACCEPTED', label: 'Accepted' },
  { id: 'EDITED_AND_ACCEPTED', label: 'Edited & Accepted' },
  { id: 'NEEDS_CLARIFICATION', label: 'Needs Clarification' },
  { id: 'REJECTED', label: 'Rejected' },
];

const EVIDENCE_STATE_FILTERS = [
  { id: 'ALL', label: 'All Evidence' },
  { id: 'SUPPORTED', label: 'Supported' },
  { id: 'INFERRED', label: 'Inferred' },
  { id: 'CONFLICTING', label: 'Conflicting' },
  { id: 'UNKNOWN', label: 'Unknown' },
];

export default function ReviewQueuePage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  // Active case selection
  const [selectedCaseId, setSelectedCaseId] = useState(searchParams.get('caseId') || '');
  const [casesList, setCasesList] = useState([]);

  // Filtering state
  const [reviewFilter, setReviewFilter] = useState('ALL');
  const [evidenceFilter, setEvidenceFilter] = useState('ALL');
  const [packFilter, setPackFilter] = useState('ALL');
  const [searchText, setSearchText] = useState('');

  // Modals & bulk actions state
  const [inspectSnapshot, setInspectSnapshot] = useState(null);
  const [selectedClaimIds, setSelectedClaimIds] = useState([]);
  const [bulkActionLoading, setBulkActionLoading] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [reviewNotesModal, setReviewNotesModal] = useState(null); // { mode: 'bulk_reject' | 'bulk_clarify', targetIds: [] }
  const [reviewNotesText, setReviewNotesText] = useState('');

  // 1. Fetch available workspaces and cases across projects
  useEffect(() => {
    async function loadCases() {
      try {
        const wsRes = await httpClient.get('/api/v1/workspaces');
        if (Array.isArray(wsRes) && wsRes.length > 0) {
          const wsId = wsRes[0].id;
          const pRes = await httpClient.get(`/api/v1/workspaces/${wsId}/projects`);
          const all = [];
          if (Array.isArray(pRes)) {
            for (const p of pRes) {
              try {
                const cRes = await httpClient.get(`/api/v1/projects/${p.id}/cases`);
                if (Array.isArray(cRes)) {
                  all.push(...cRes);
                }
              } catch (_) {}
            }
          }
          setCasesList(all);
          const urlCase = searchParams.get('caseId');
          if (urlCase && all.some((c) => c.id === urlCase)) {
            setSelectedCaseId(urlCase);
          } else if (!selectedCaseId && all.length > 0) {
            setSelectedCaseId(all[0].id);
          }
        }
      } catch (err) {
        console.error('Failed to load cases:', err);
      }
    }
    loadCases();
  }, []);

  useEffect(() => {
    const urlCaseId = searchParams.get('caseId');
    if (urlCaseId && urlCaseId !== selectedCaseId) {
      setSelectedCaseId(urlCaseId);
    }
  }, [searchParams]);

  useEffect(() => {
    setSelectedClaimIds([]);
    setActionError(null);
  }, [selectedCaseId, reviewFilter, evidenceFilter, packFilter, searchText]);

  const handleCaseChange = (e) => {
    const newCaseId = e.target.value;
    setSelectedCaseId(newCaseId);
    setSearchParams({ caseId: newCaseId });
  };

  // 2. Fetch Review Queue Summary for active case
  const { data: queueSummary, isLoading: summaryLoading } = useQuery({
    queryKey: ['review-queue-summary', selectedCaseId],
    queryFn: () => reviewApi.getReviewQueue(selectedCaseId),
    enabled: !!selectedCaseId,
  });

  // 3. Fetch Transfer Packs for active case
  const { data: casePacks } = useQuery({
    queryKey: ['case-packs', selectedCaseId],
    queryFn: () => transferPackApi.listPacks(selectedCaseId),
    enabled: !!selectedCaseId,
  });

  // 4. Fetch Claims for active case
  const { data: claims, isLoading: claimsLoading } = useQuery({
    queryKey: ['case-claims', selectedCaseId],
    queryFn: () => evidenceApi.listClaimsForCase(selectedCaseId),
    enabled: !!selectedCaseId,
  });

  // 5. Fetch Version History for active case
  const { data: versions } = useQuery({
    queryKey: ['case-versions', selectedCaseId],
    queryFn: () => reviewApi.listVersions(selectedCaseId),
    enabled: !!selectedCaseId,
  });

  // Review Claim Mutation
  const reviewMutation = useMutation({
    mutationFn: ({ claimId, data }) => reviewApi.reviewClaim(claimId, data),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: ['case-claims', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-questions', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      const msg = err.data?.detail || err.data?.error?.message || err.message || 'Review action failed';
      setActionError(msg);
      alert(msg);
    },
  });

  // Update Claim Mutation
  const updateClaimMutation = useMutation({
    mutationFn: ({ claimId, data }) => evidenceApi.updateClaim(claimId, data),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: ['case-claims', selectedCaseId] });
    },
    onError: (err) => {
      const msg = err.data?.detail || err.data?.error?.message || err.message || 'Update claim failed';
      setActionError(msg);
      alert(msg);
    },
  });

  // Move Claim Mutation
  const moveClaimMutation = useMutation({
    mutationFn: ({ claimId, targetPackId }) =>
      transferPackApi.moveClaims(targetPackId, claimId),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: ['case-claims', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', selectedCaseId] });
    },
    onError: (err) => {
      const msg = err.data?.detail || err.data?.error?.message || err.message || 'Move claim failed';
      setActionError(msg);
      alert(msg);
    },
  });

  // Create Approved Version Mutation
  const createVersionMutation = useMutation({
    mutationFn: (data) => reviewApi.createVersion(selectedCaseId, data),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: ['case-versions', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-claims', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      const msg = err.data?.detail || err.data?.error?.message || err.message || 'Failed to approve version';
      setActionError(msg);
      alert(msg);
    },
  });

  // Filtered Claims
  const filteredClaims = useMemo(() => {
    if (!Array.isArray(claims)) return [];
    return claims.filter((c) => {
      if (reviewFilter !== 'ALL' && c.review_state !== reviewFilter) return false;
      if (evidenceFilter !== 'ALL' && c.evidence_state !== evidenceFilter) return false;
      if (packFilter !== 'ALL' && c.transfer_pack_id !== packFilter) return false;
      if (searchText.trim()) {
        const query = searchText.toLowerCase();
        const matchesTitle = (c.title || '').toLowerCase().includes(query);
        const matchesBody = (c.body_text || '').toLowerCase().includes(query);
        if (!matchesTitle && !matchesBody) return false;
      }
      return true;
    });
  }, [claims, reviewFilter, evidenceFilter, packFilter, searchText]);

  // Bulk Selection Handlers
  const toggleSelectClaim = useCallback((claimId) => {
    setSelectedClaimIds((prev) =>
      prev.includes(claimId) ? prev.filter((id) => id !== claimId) : [...prev, claimId]
    );
  }, []);

  const handleSelectAllFiltered = useCallback(() => {
    if (selectedClaimIds.length === filteredClaims.length) {
      setSelectedClaimIds([]);
    } else {
      setSelectedClaimIds(filteredClaims.map((c) => c.id));
    }
  }, [selectedClaimIds.length, filteredClaims]);

  const handleBulkApprove = async () => {
    if (selectedClaimIds.length === 0) return;
    setBulkActionLoading(true);
    setActionError(null);
    try {
      await Promise.all(
        selectedClaimIds.map((claimId) => reviewApi.reviewClaim(claimId, { action: 'accept' }))
      );
      setSelectedClaimIds([]);
      queryClient.invalidateQueries({ queryKey: ['case-claims', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    } catch (err) {
      const msg = err.data?.detail || err.data?.error?.message || err.message || 'Bulk approve failed';
      setActionError(msg);
    } finally {
      setBulkActionLoading(false);
    }
  };

  const handleOpenBulkNotesModal = (mode) => {
    if (selectedClaimIds.length === 0) return;
    setReviewNotesText('');
    setReviewNotesModal({ mode, targetIds: [...selectedClaimIds] });
  };

  const handleConfirmReviewNotes = async () => {
    if (!reviewNotesModal) return;
    if (!reviewNotesText.trim()) {
      alert('Review notes / reason is required.');
      return;
    }
    const { mode, targetIds } = reviewNotesModal;
    const action = mode === 'bulk_reject' ? 'reject' : 'needs_clarification';
    setBulkActionLoading(true);
    setActionError(null);
    try {
      await Promise.all(
        targetIds.map((claimId) =>
          reviewApi.reviewClaim(claimId, { action, reason: reviewNotesText.trim() })
        )
      );
      setSelectedClaimIds([]);
      setReviewNotesModal(null);
      setReviewNotesText('');
      queryClient.invalidateQueries({ queryKey: ['case-claims', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-questions', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    } catch (err) {
      const msg = err.data?.detail || err.data?.error?.message || err.message || 'Bulk review action failed';
      setActionError(msg);
    } finally {
      setBulkActionLoading(false);
    }
  };

  const handleInspectVersion = async (versionId) => {
    try {
      const v = await reviewApi.getVersion(versionId);
      setInspectSnapshot(v);
    } catch (err) {
      console.error('Failed to fetch version detail:', err);
    }
  };

  const selectedCase = casesList.find((c) => c.id === selectedCaseId);

  return (
    <div className={styles.page}>
      {/* Top Header */}
      <div className={styles.header}>
        <div className={styles.titleArea}>
          <h2>
            <CheckSquare size={24} style={{ color: 'var(--color-accent)' }} />
            Review Queue & Verification
          </h2>
          <p className={styles.subtitle}>
            Conduct peer review of synthesized claims, resolve preconditions, and freeze audit-grade immutable version snapshots.
          </p>
        </div>

        {/* Case Selector */}
        <div className={styles.caseSelectorWrap}>
          <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
            Select Handover Case:
          </label>
          <select
            className={styles.caseSelect}
            value={selectedCaseId}
            onChange={handleCaseChange}
          >
            {casesList.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.case_number} — {c.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Action Error Banner */}
      {actionError && (
        <div className={styles.errorBanner}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertTriangle size={16} />
            <span>{actionError}</span>
          </div>
          <button
            className={styles.closeBtn}
            onClick={() => setActionError(null)}
            title="Dismiss error"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Summary Stats Grid */}
      <div className={styles.statsGrid}>
        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span>Total Claims</span>
            <FileCheck2 size={16} />
          </div>
          <span className={styles.statValue}>
            {summaryLoading ? '…' : queueSummary?.total_claims ?? 0}
          </span>
        </div>

        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span>Pending Review</span>
            <Clock size={16} style={{ color: 'var(--color-warning)' }} />
          </div>
          <span className={`${styles.statValue} ${styles.statValuePending}`}>
            {summaryLoading ? '…' : queueSummary?.pending_review_count ?? 0}
          </span>
        </div>

        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span>Accepted</span>
            <CheckCircle2 size={16} style={{ color: 'var(--color-success)' }} />
          </div>
          <span className={`${styles.statValue} ${styles.statValueAccepted}`}>
            {summaryLoading
              ? '…'
              : (queueSummary?.accepted_count || 0) + (queueSummary?.edited_and_accepted_count || 0)}
          </span>
        </div>

        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span>Clarifications</span>
            <HelpCircle size={16} style={{ color: 'var(--color-info)' }} />
          </div>
          <span className={`${styles.statValue} ${styles.statValueClarify}`}>
            {summaryLoading ? '…' : queueSummary?.needs_clarification_count ?? 0}
          </span>
        </div>

        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span>Rejected</span>
            <XCircle size={16} style={{ color: 'var(--color-error)' }} />
          </div>
          <span className={`${styles.statValue} ${styles.statValueRejected}`}>
            {summaryLoading ? '…' : queueSummary?.rejected_count ?? 0}
          </span>
        </div>

        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span>Unresolved Questions</span>
            <HelpCircle size={16} style={{ color: (queueSummary?.open_questions_count || 0) + (queueSummary?.awaiting_question_review_count || 0) > 0 ? 'var(--color-warning)' : 'var(--color-success)' }} />
          </div>
          <span className={styles.statValue}>
            {summaryLoading
              ? '…'
              : (queueSummary?.open_questions_count || 0) + (queueSummary?.awaiting_question_review_count || 0)}
          </span>
        </div>
      </div>

      {/* Authoritative Approval Readiness & Lead Override Panel */}
      <ApprovalPreflightPanel
        queueSummary={queueSummary}
        onApproveVersion={(payload) => createVersionMutation.mutateAsync(payload)}
        isSubmitting={createVersionMutation.isPending}
        styles={styles}
      />

      {/* Filter Toolbar */}
      <div className={styles.controlsBar}>
        <div className={styles.filterChipsRow}>
          <span style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--color-text-muted)', marginRight: '6px' }}>
            Review State:
          </span>
          {REVIEW_STATE_FILTERS.map((f) => (
            <button
              key={f.id}
              className={`${styles.filterChip} ${reviewFilter === f.id ? styles.filterChipActive : ''}`}
              onClick={() => setReviewFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className={styles.secondaryFiltersRow}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>Evidence:</span>
            <select
              className={styles.selectInput}
              value={evidenceFilter}
              onChange={(e) => setEvidenceFilter(e.target.value)}
            >
              {EVIDENCE_STATE_FILTERS.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.label}
                </option>
              ))}
            </select>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>Transfer Pack:</span>
            <select
              className={styles.selectInput}
              value={packFilter}
              onChange={(e) => setPackFilter(e.target.value)}
            >
              <option value="ALL">All Transfer Packs</option>
              {(casePacks || []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginLeft: 'auto' }}>
            <Search size={14} style={{ color: 'var(--color-text-muted)' }} />
            <input
              type="text"
              placeholder="Search claims…"
              className={styles.searchInput}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
            />
            {searchText && (
              <button
                className={styles.clearSearchBtn}
                onClick={() => setSearchText('')}
                title="Clear search"
              >
                <X size={12} />
              </button>
            )}
            {filteredClaims.length > 0 && (
              <button
                className={styles.filterChip}
                onClick={handleSelectAllFiltered}
                style={{ fontWeight: 600, marginLeft: '8px' }}
                title="Select all currently visible filtered claims"
              >
                {selectedClaimIds.length === filteredClaims.length ? 'Deselect All' : `Select All (${filteredClaims.length})`}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Bulk Actions Floating Toolbar */}
      {selectedClaimIds.length > 0 && (
        <div className={styles.bulkActionBar}>
          <div className={styles.bulkActionInfo}>
            <CheckSquare size={16} />
            <span>{selectedClaimIds.length} claim{selectedClaimIds.length === 1 ? '' : 's'} selected</span>
          </div>
          <div className={styles.bulkActionBtns}>
            <button
              className={styles.bulkApproveBtn}
              onClick={handleBulkApprove}
              disabled={bulkActionLoading}
              title="Bulk approve selected claims"
            >
              <CheckCircle2 size={13} /> {bulkActionLoading ? 'Processing…' : 'Bulk Approve'}
            </button>
            <button
              className={styles.bulkRejectBtn}
              onClick={() => handleOpenBulkNotesModal('bulk_reject')}
              disabled={bulkActionLoading}
              title="Bulk reject selected claims with review notes"
            >
              <XCircle size={13} /> Bulk Reject
            </button>
            <button
              className={styles.bulkClearBtn}
              onClick={() => setSelectedClaimIds([])}
              title="Clear selection"
            >
              Clear Selection
            </button>
          </div>
        </div>
      )}

      {/* Claims List */}
      {claimsLoading ? (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--color-text-muted)' }}>
          Loading review claims…
        </div>
      ) : filteredClaims.length === 0 ? (
        <div className={styles.emptyState}>
          <Layers size={36} />
          <h3>No Claims Match Filters</h3>
          <p>Change your filter criteria or select another review state above.</p>
          {(reviewFilter !== 'ALL' || evidenceFilter !== 'ALL' || packFilter !== 'ALL' || searchText) && (
            <button
              className={styles.clearFiltersBtn}
              onClick={() => {
                setReviewFilter('ALL');
                setEvidenceFilter('ALL');
                setPackFilter('ALL');
                setSearchText('');
              }}
            >
              Reset All Filters
            </button>
          )}
        </div>
      ) : (
        <div className={styles.claimsList}>
          {filteredClaims.map((claim) => (
            <div key={claim.id} className={styles.claimRowWrap}>
              <div className={styles.claimCheckboxWrap}>
                <input
                  type="checkbox"
                  className={styles.claimCheckbox}
                  checked={selectedClaimIds.includes(claim.id)}
                  onChange={() => toggleSelectClaim(claim.id)}
                  aria-label={`Select claim ${claim.title}`}
                />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <ClaimCard
                  claim={claim}
                  availablePacks={casePacks || []}
                  enableReview={true}
                  onReviewClaim={(claimId, data) => reviewMutation.mutateAsync({ claimId, data })}
                  onUpdateClaim={(claimId, data) => updateClaimMutation.mutateAsync({ claimId, data })}
                  onMoveClaim={(claimId, targetPackId) => moveClaimMutation.mutateAsync({ claimId, targetPackId })}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Version History Section */}
      <div className={styles.versionsSection}>
        <div className={styles.versionsHeader}>
          <h3 className={styles.versionsTitle}>
            <History size={20} style={{ color: 'var(--color-accent)' }} />
            Approved Version History ({versions?.length || 0})
          </h3>
          {selectedCase && (
            <Link
              to={`/cases/${selectedCase.id}`}
              style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--color-accent-text)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              Open Full Case #{selectedCase.case_number} <ArrowRight size={12} />
            </Link>
          )}
        </div>

        {!Array.isArray(versions) || versions.length === 0 ? (
          <div className={styles.emptyState} style={{ padding: '2rem' }}>
            <ShieldCheck size={28} />
            <p>No immutable versions have been approved for this case yet.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
            {versions.map((v) => (
              <div key={v.id} className={styles.versionCard}>
                <div className={styles.versionTop}>
                  <div className={styles.versionBadge}>
                    <span>Version {v.version_number}</span>
                    {v.is_current ? (
                      <span className={styles.currentPill}>Current Active</span>
                    ) : (
                      <span className={styles.supersededPill}>Superseded</span>
                    )}
                  </div>
                  <div className={styles.versionMeta}>
                    <span>Approved by {v.approved_by_name || 'Reviewer'}</span>
                    <span>•</span>
                    <span>{v.approved_at ? new Date(v.approved_at).toLocaleString() : '—'}</span>
                    <span>•</span>
                    <span>{v.total_packs} Packs</span>
                    <span>•</span>
                    <span>{v.total_claims} Claims</span>
                  </div>
                </div>

                {v.amendment_reason && (
                  <div className={styles.versionReason}>
                    <strong>Amendment Reason:</strong> {v.amendment_reason}
                  </div>
                )}

                <button
                  className={styles.viewSnapshotBtn}
                  onClick={() => handleInspectVersion(v.id)}
                >
                  <Eye size={12} /> View Frozen Snapshot JSON
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Snapshot JSON Inspection Modal */}
      {inspectSnapshot && (
        <div className={styles.modalOverlay} onClick={() => setInspectSnapshot(null)}>
          <div
            className={styles.modalContent}
            style={{ maxWidth: '800px' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.modalHeader}>
              <h3>Frozen Snapshot — Version {inspectSnapshot.version_number}</h3>
              <button className={styles.closeBtn} onClick={() => setInspectSnapshot(null)}>
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                Approved at: {inspectSnapshot.approved_at ? new Date(inspectSnapshot.approved_at).toLocaleString() : '—'} by {inspectSnapshot.approved_by_name}
              </div>
              <pre className={styles.jsonViewer}>
                {JSON.stringify(inspectSnapshot.snapshot_json, null, 2)}
              </pre>
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.approveBtn}
                onClick={() => setInspectSnapshot(null)}
              >
                Close Snapshot
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Review Notes Modal for Bulk Actions */}
      {reviewNotesModal && (
        <div className={styles.modalOverlay} onClick={() => setReviewNotesModal(null)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>
                {reviewNotesModal.mode === 'bulk_reject' ? 'Bulk Reject Claims' : 'Bulk Request Clarification'}
              </h3>
              <button className={styles.closeBtn} onClick={() => setReviewNotesModal(null)}>
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)', margin: 0 }}>
                Applying review decision to {reviewNotesModal.targetIds.length} selected claim(s). Please provide review notes / justification:
              </p>
              <textarea
                className={styles.notesTextarea}
                rows={4}
                placeholder="Enter review notes and rejection rationale..."
                value={reviewNotesText}
                onChange={(e) => setReviewNotesText(e.target.value)}
                autoFocus
              />
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.bulkClearBtn}
                onClick={() => setReviewNotesModal(null)}
              >
                Cancel
              </button>
              <button
                className={reviewNotesModal.mode === 'bulk_reject' ? styles.bulkRejectBtn : styles.bulkApproveBtn}
                onClick={handleConfirmReviewNotes}
                disabled={bulkActionLoading || !reviewNotesText.trim()}
              >
                {bulkActionLoading ? 'Submitting…' : 'Confirm Review'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
