import { useState, useMemo, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, Link } from 'react-router-dom';
import {
  CheckSquare,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  Clock,
  HelpCircle,
  XCircle,
  FolderKanban,
  FileCheck2,
  Layers,
  History,
  X,
  Eye,
  Search,
  Filter,
  ArrowRight,
} from 'lucide-react';
import { httpClient } from '../../api/httpClient';
import { reviewApi } from '../../api/review.api';
import { evidenceApi } from '../../api/evidence.api';
import { transferPackApi } from '../../api/transferPack.api';
import { ClaimCard } from '../../components/claim-card/claim-card';
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

  // Modals state
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [amendmentReason, setAmendmentReason] = useState('');
  const [inspectSnapshot, setInspectSnapshot] = useState(null);

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
          if (!selectedCaseId && all.length > 0) {
            setSelectedCaseId(all[0].id);
          }
        }
      } catch (err) {
        console.error('Failed to load cases:', err);
      }
    }
    loadCases();
  }, []);

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
      queryClient.invalidateQueries({ queryKey: ['case-claims', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-questions', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Review action failed');
    },
  });

  // Update Claim Mutation
  const updateClaimMutation = useMutation({
    mutationFn: ({ claimId, data }) => evidenceApi.updateClaim(claimId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-claims', selectedCaseId] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Update claim failed');
    },
  });

  // Move Claim Mutation
  const moveClaimMutation = useMutation({
    mutationFn: ({ claimId, targetPackId }) =>
      transferPackApi.moveClaims(targetPackId, claimId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-claims', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', selectedCaseId] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Move claim failed');
    },
  });

  // Create Approved Version Mutation
  const createVersionMutation = useMutation({
    mutationFn: (data) => reviewApi.createVersion(selectedCaseId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-versions', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-claims', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      setShowApproveModal(false);
      setAmendmentReason('');
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to approve version');
    },
  });

  // Filtered Claims
  const filteredClaims = useMemo(() => {
    if (!claims) return [];
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
            <Clock size={16} style={{ color: '#fbbf24' }} />
          </div>
          <span className={`${styles.statValue} ${styles.statValuePending}`}>
            {summaryLoading ? '…' : queueSummary?.pending_review_count ?? 0}
          </span>
        </div>

        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span>Accepted</span>
            <CheckCircle2 size={16} style={{ color: '#34d399' }} />
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
            <HelpCircle size={16} style={{ color: '#60a5fa' }} />
          </div>
          <span className={`${styles.statValue} ${styles.statValueClarify}`}>
            {summaryLoading ? '…' : queueSummary?.needs_clarification_count ?? 0}
          </span>
        </div>

        <div className={styles.statCard}>
          <div className={styles.statHeader}>
            <span>Rejected</span>
            <XCircle size={16} style={{ color: '#f87171' }} />
          </div>
          <span className={`${styles.statValue} ${styles.statValueRejected}`}>
            {summaryLoading ? '…' : queueSummary?.rejected_count ?? 0}
          </span>
        </div>
      </div>

      {/* Approval Readiness Banner */}
      {queueSummary && (
        <div
          className={`${styles.readinessBanner} ${
            queueSummary.can_approve ? styles.readinessReady : styles.readinessBlocked
          }`}
        >
          <div className={styles.readinessInfo}>
            {queueSummary.can_approve ? (
              <CheckCircle2 size={24} className={styles.readinessIconReady} />
            ) : (
              <AlertTriangle size={24} className={styles.readinessIconBlocked} />
            )}
            <div>
              <div className={styles.readinessTitle}>
                {queueSummary.can_approve
                  ? 'All Review Preconditions Satisfied'
                  : 'Approval Preconditions Pending'}
              </div>
              {queueSummary.can_approve ? (
                <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                  All transfer packs and claims have been verified. You may freeze an immutable version snapshot (v
                  {(queueSummary.current_version_number || 0) + 1}).
                </p>
              ) : (
                <ul className={styles.blockingList}>
                  {queueSummary.blocking_reasons.map((reason, idx) => (
                    <li key={idx}>{reason}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <button
            className={styles.approveBtn}
            onClick={() => setShowApproveModal(true)}
            disabled={!queueSummary.can_approve || createVersionMutation.isPending}
          >
            <ShieldCheck size={16} />
            Approve Version Snapshot
          </button>
        </div>
      )}

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
          </div>
        </div>
      </div>

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
        </div>
      ) : (
        <div className={styles.claimsList}>
          {filteredClaims.map((claim) => (
            <ClaimCard
              key={claim.id}
              claim={claim}
              availablePacks={casePacks || []}
              enableReview={true}
              onReviewClaim={(claimId, data) => reviewMutation.mutateAsync({ claimId, data })}
              onUpdateClaim={(claimId, data) => updateClaimMutation.mutateAsync({ claimId, data })}
              onMoveClaim={(claimId, targetPackId) => moveClaimMutation.mutateAsync({ claimId, targetPackId })}
            />
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

        {!versions || versions.length === 0 ? (
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
                    <span>{new Date(v.approved_at).toLocaleString()}</span>
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

      {/* Approve Version Modal */}
      {showApproveModal && (
        <div className={styles.modalOverlay} onClick={() => setShowApproveModal(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Approve Handover Version</h3>
              <button className={styles.closeBtn} onClick={() => setShowApproveModal(false)}>
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)', margin: 0 }}>
                Approving will create an immutable, cryptographic-grade JSON snapshot of all Transfer Packs,
                claims, evidence mappings, and participant assignments. The case status will transition to <strong>APPROVED</strong>.
              </p>

              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: '6px' }}>
                  Amendment / Approval Notes (optional)
                </label>
                <textarea
                  rows={3}
                  placeholder="e.g. Initial engineering review approved by Tech Lead; all runbooks verified."
                  value={amendmentReason}
                  onChange={(e) => setAmendmentReason(e.target.value)}
                  style={{
                    width: '100%',
                    padding: 'var(--space-sm)',
                    backgroundColor: 'var(--color-bg-primary)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--color-text-primary)',
                    fontSize: 'var(--text-sm)',
                    fontFamily: 'var(--font-sans)',
                  }}
                />
              </div>
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.filterChip}
                onClick={() => setShowApproveModal(false)}
              >
                Cancel
              </button>
              <button
                className={styles.approveBtn}
                onClick={() =>
                  createVersionMutation.mutate({
                    amendment_reason: amendmentReason.trim() || undefined,
                  })
                }
                disabled={createVersionMutation.isPending}
              >
                <ShieldCheck size={16} />
                {createVersionMutation.isPending ? 'Freezing Snapshot…' : 'Confirm & Freeze Version'}
              </button>
            </div>
          </div>
        </div>
      )}

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
                Approved at: {new Date(inspectSnapshot.approved_at).toLocaleString()} by {inspectSnapshot.approved_by_name}
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
    </div>
  );
}
