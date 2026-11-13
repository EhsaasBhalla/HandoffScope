import { useState, useMemo, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  FolderKanban,
  GitBranch,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  FileStack,
  Layers,
  Settings,
  Plus,
  GitMerge,
  ArrowRight,
  UserCheck,
  MessageSquare,
  AlertCircle,
} from 'lucide-react';
import { transferPackApi } from '../../api/transferPack.api';
import { evidenceApi } from '../../api/evidence.api';
import { questionApi } from '../../api/question.api';
import { reviewApi } from '../../api/review.api';
import { usePermissions } from '../../hooks/usePermissions';
import { ClaimCard } from '../../components/claim-card/claim-card';
import styles from './transfer-pack-detail.module.css';

const CLAIM_TYPES = [
  { id: 'ALL', label: 'All Claims' },
  { id: 'WORK_ITEM', label: 'Work Items' },
  { id: 'DECISION', label: 'Decisions' },
  { id: 'DEPENDENCY', label: 'Dependencies' },
  { id: 'RISK', label: 'Risks' },
  { id: 'OPERATIONAL_NOTE', label: 'Operational Notes' },
  { id: 'KNOWLEDGE_GAP', label: 'Knowledge Gaps' },
  { id: 'NEXT_ACTION', label: 'Next Actions' },
];

export default function TransferPackDetailPage() {
  const { caseId, packId } = useParams();
  const queryClient = useQueryClient();
  const { hasCapability } = usePermissions();

  const canManagePack = hasCapability('pack.manage') || hasCapability('case.manage');
  const canReview = hasCapability('review.submit') || hasCapability('case.approve');
  const canCreateQuestion = hasCapability('question.create');

  const [selectedType, setSelectedType] = useState('ALL');

  // Modals state
  const [showEditModal, setShowEditModal] = useState(false);
  const [showQuestionModal, setShowQuestionModal] = useState(false);
  const [showMergeModal, setShowMergeModal] = useState(false);

  // Edit Pack form
  const [packName, setPackName] = useState('');
  const [packDesc, setPackDesc] = useState('');
  const [packArea, setPackArea] = useState('');
  const [editError, setEditError] = useState('');

  // Ask Question form
  const [qText, setQText] = useState('');
  const [qWhy, setQWhy] = useState('');
  const [qPriority, setQPriority] = useState('MEDIUM');
  const [questionError, setQuestionError] = useState('');

  // Merge form
  const [sourcePackIdToMerge, setSourcePackIdToMerge] = useState('');
  const [mergeError, setMergeError] = useState('');

  const closeEditModal = () => {
    setShowEditModal(false);
    setEditError('');
  };

  const closeMergeModal = () => {
    setShowMergeModal(false);
    setSourcePackIdToMerge('');
    setMergeError('');
  };

  const closeQuestionModal = () => {
    setShowQuestionModal(false);
    setQText('');
    setQWhy('');
    setQPriority('MEDIUM');
    setQuestionError('');
  };

  // 1. Fetch Transfer Pack details
  const { data: pack, isLoading: packLoading } = useQuery({
    queryKey: ['transfer-pack', packId],
    queryFn: () => transferPackApi.getPack(packId),
    enabled: !!packId,
  });

  // 2. Fetch all packs for the case (for moving claims and merging)
  const { data: allPacks } = useQuery({
    queryKey: ['case-packs', caseId],
    queryFn: () => transferPackApi.listPacks(caseId),
    enabled: !!caseId,
  });

  // 3. Fetch all claims for this pack
  const { data: claims, isLoading: claimsLoading } = useQuery({
    queryKey: ['pack-claims', packId],
    queryFn: () => evidenceApi.listClaimsForPack(packId),
    enabled: !!packId,
  });

  // 4. Fetch questions linked to this pack or case
  const { data: packQuestions } = useQuery({
    queryKey: ['pack-questions', packId],
    queryFn: async () => {
      const qs = await questionApi.listQuestions({ case_id: caseId });
      const list = Array.isArray(qs) ? qs : qs?.data || [];
      return list.filter((q) => q.transfer_pack_id === packId);
    },
    enabled: !!caseId && !!packId,
  });

  // Mutations
  const updatePackMutation = useMutation({
    mutationFn: (data) => transferPackApi.updatePack(packId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transfer-pack', packId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      closeEditModal();
    },
    onError: (err) => {
      setEditError(err.data?.detail || err.message || 'Failed to update Transfer Pack');
    },
  });

  const transitionStatusMutation = useMutation({
    mutationFn: (status) => transferPackApi.transitionStatus(packId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transfer-pack', packId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to transition pack status');
    },
  });

  const moveClaimMutation = useMutation({
    mutationFn: ({ claimId, targetPackId }) =>
      transferPackApi.moveClaims(targetPackId, claimId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pack-claims', packId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['transfer-pack', packId] });
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to move claim');
    },
  });

  const updateClaimMutation = useMutation({
    mutationFn: ({ claimId, data }) => evidenceApi.updateClaim(claimId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pack-claims', packId] });
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['transfer-pack', packId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to update claim');
    },
  });

  const reviewClaimMutation = useMutation({
    mutationFn: ({ claimId, data }) => reviewApi.reviewClaim(claimId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pack-claims', packId] });
      queryClient.invalidateQueries({ queryKey: ['transfer-pack', packId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['pack-questions', packId] });
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to review claim');
    },
  });

  const mergePacksMutation = useMutation({
    mutationFn: (sourcePackId) => transferPackApi.mergePacks(packId, sourcePackId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pack-claims', packId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['transfer-pack', packId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      closeMergeModal();
    },
    onError: (err) => {
      setMergeError(err.data?.detail || err.message || 'Failed to merge packs');
    },
  });

  const askQuestionMutation = useMutation({
    mutationFn: (data) => questionApi.createQuestion(caseId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pack-questions', packId] });
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      closeQuestionModal();
    },
    onError: (err) => {
      setQuestionError(err.data?.detail || err.message || 'Failed to submit question');
    },
  });

  // Stabilized claim handlers for memoized ClaimCard
  const handleMoveClaim = useCallback(
    (claimId, targetPackId) => moveClaimMutation.mutateAsync({ claimId, targetPackId }),
    [moveClaimMutation]
  );

  const handleUpdateClaim = useCallback(
    (claimId, data) => updateClaimMutation.mutateAsync({ claimId, data }),
    [updateClaimMutation]
  );

  const handleReviewClaim = useCallback(
    (claimId, data) => reviewClaimMutation.mutateAsync({ claimId, data }),
    [reviewClaimMutation]
  );

  // Calculate evidence state breakdown
  const stats = useMemo(() => {
    const list = claims || [];
    return {
      total: list.length,
      supported: list.filter((c) => c.evidence_state === 'SUPPORTED').length,
      inferred: list.filter((c) => c.evidence_state === 'INFERRED').length,
      conflicting: list.filter((c) => c.evidence_state === 'CONFLICTING').length,
      unknown: list.filter((c) => c.evidence_state === 'UNKNOWN').length,
    };
  }, [claims]);

  // Filter claims
  const filteredClaims = useMemo(() => {
    if (!claims) return [];
    if (selectedType === 'ALL') return claims;
    return claims.filter((c) => c.claim_type === selectedType);
  }, [claims, selectedType]);

  const openEditModal = () => {
    if (pack) {
      setPackName(pack.name);
      setPackDesc(pack.description || '');
      setPackArea(pack.component_area || '');
    }
    setShowEditModal(true);
  };

  const getNextStatusAction = (currentStatus) => {
    switch (currentStatus) {
      case 'DRAFT':
        return { label: 'Ready for Review', target: 'READY_FOR_REVIEW' };
      case 'READY_FOR_REVIEW':
        return { label: 'Begin Review', target: 'UNDER_REVIEW' };
      case 'UNDER_REVIEW':
        return { label: 'Approve Pack', target: 'APPROVED' };
      default:
        return null;
    }
  };

  if (packLoading) {
    return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--color-text-muted)' }}>Loading Transfer Pack…</div>;
  }

  if (!pack) {
    return (
      <div style={{ textAlign: 'center', padding: '3rem' }}>
        <h3>Transfer Pack not found</h3>
        <Link to={`/cases/${caseId}`}>Return to Handover Case</Link>
      </div>
    );
  }

  const nextStatus = getNextStatusAction(pack.status);

  return (
    <div className={styles.container}>
      {/* Back to Case */}
      <Link to={`/cases/${caseId}`} className={styles.backLink}>
        <ArrowLeft size={14} /> Back to Handover Case
      </Link>

      {/* Pack Header Card */}
      <div className={styles.headerCard}>
        <div className={styles.headerTop}>
          <div className={styles.titleArea}>
            <div className={styles.titleRow}>
              <h2>{pack.name}</h2>
              {pack.component_area && (
                <span className={styles.areaBadge}>{pack.component_area}</span>
              )}
              <span className={styles.statusBadge}>{pack.status}</span>
              {pack.is_blocked && (
                <span className={styles.blockedBadge}>
                  <AlertCircle size={12} style={{ display: 'inline', marginRight: '4px' }} />
                  Blocked: {pack.blocked_reason || 'Action required'}
                </span>
              )}
            </div>
            <p className={styles.packDesc}>{pack.description || 'No description provided.'}</p>
          </div>

          <div className={styles.headerActions}>
            {canManagePack && (
              <button className={styles.actionButton} onClick={openEditModal}>
                <Settings size={14} /> Edit Pack
              </button>
            )}
            {canManagePack && allPacks && allPacks.length > 1 && (
              <button className={styles.actionButton} onClick={() => setShowMergeModal(true)}>
                <GitMerge size={14} /> Merge Pack
              </button>
            )}
            {nextStatus && (canManagePack || canReview) && (
              <button
                className={`${styles.actionButton} ${styles.primaryBtn}`}
                onClick={() => transitionStatusMutation.mutate(nextStatus.target)}
                disabled={transitionStatusMutation.isPending}
              >
                <CheckCircle2 size={14} /> {nextStatus.label}
              </button>
            )}
          </div>
        </div>

        <div className={styles.packMetaGrid}>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>Historical Owner</span>
            <span className={styles.metaValue}>{pack.recorded_owner_name || 'Unassigned'}</span>
          </div>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>Suggested Successor</span>
            <span className={styles.metaValue}>{pack.suggested_successor_name || 'Pending assignment'}</span>
          </div>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>Claims Count</span>
            <span className={styles.metaValue}>{stats.total} Grounded Units</span>
          </div>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>Created Date</span>
            <span className={styles.metaValue}>
              {pack.created_at ? new Date(pack.created_at).toLocaleDateString() : 'N/A'}
            </span>
          </div>
        </div>
      </div>

      {/* Grounded Evidence Breakdown Bar */}
      <div className={styles.breakdownBar}>
        <span className={styles.breakdownTitle}>Evidence Integrity Profile ({stats.total} claims)</span>
        <div className={styles.breakdownPills}>
          <div className={styles.statPill} title="Fully grounded in direct source records">
            <span className={`${styles.statDot} ${styles.dotSupported}`} />
            <span>{stats.supported} Supported</span>
          </div>
          <div className={styles.statPill} title="Derived or inferred from related activity">
            <span className={`${styles.statDot} ${styles.dotInferred}`} />
            <span>{stats.inferred} Inferred</span>
          </div>
          {stats.conflicting > 0 && (
            <div className={styles.statPill} title="Directly conflicting evidence found">
              <span className={`${styles.statDot} ${styles.dotConflicting}`} />
              <span>{stats.conflicting} Conflicting</span>
            </div>
          )}
          {stats.unknown > 0 && (
            <div className={styles.statPill} title="Unverified claims or knowledge gaps">
              <span className={`${styles.statDot} ${styles.dotUnknown}`} />
              <span>{stats.unknown} Unknown</span>
            </div>
          )}
        </div>
      </div>

      {/* Section Filter Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.filterChips}>
          {CLAIM_TYPES.map((t) => (
            <button
              key={t.id}
              className={`${styles.filterChip} ${selectedType === t.id ? styles.filterChipActive : ''}`}
              onClick={() => setSelectedType(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
          Showing {filteredClaims.length} of {stats.total} claims
        </span>
      </div>

      {/* Claims Stream */}
      {claimsLoading ? (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--color-text-muted)' }}>
          Loading grounded claims…
        </div>
      ) : filteredClaims.length === 0 ? (
        <div className={styles.emptyState}>
          <Layers size={32} />
          <h3>No claims found in this category</h3>
          <p>Select "All Claims" or edit claims to assign them to this category.</p>
        </div>
      ) : (
        <div className={styles.claimsList}>
          {filteredClaims.map((claim) => (
            <ClaimCard
              key={claim.id}
              claim={claim}
              availablePacks={allPacks || []}
              onMoveClaim={canManagePack ? handleMoveClaim : undefined}
              onUpdateClaim={canManagePack ? handleUpdateClaim : undefined}
              enableReview={canReview}
              onReviewClaim={canReview ? handleReviewClaim : undefined}
            />
          ))}
        </div>
      )}

      {/* Knowledge Gaps & Questions Section */}
      <div className={styles.questionsSection}>
        <div className={styles.questionsHeader}>
          <h3 className={styles.questionsTitle}>
            <HelpCircle size={18} style={{ color: 'var(--color-accent)' }} />
            Knowledge Gap Questions ({packQuestions?.length || 0})
          </h3>
          {canCreateQuestion && (
            <button
              className={`${styles.actionButton} ${styles.primaryBtn}`}
              onClick={() => setShowQuestionModal(true)}
            >
              <Plus size={14} /> Ask Question for this Pack
            </button>
          )}
        </div>

        {packQuestions && packQuestions.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            {packQuestions.map((q) => (
              <div key={q.id} className={styles.questionItem}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, fontSize: '14px', color: 'var(--color-text-primary)' }}>
                    {q.question_text}
                  </span>
                  <span className={styles.statusBadge}>{q.status}</span>
                </div>
                {q.why_it_matters && (
                  <p style={{ margin: 0, fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                    {q.why_it_matters}
                  </p>
                )}
                {q.responses && q.responses.length > 0 && (
                  <div style={{ marginTop: '6px', padding: '8px', backgroundColor: 'var(--color-bg-primary)', borderRadius: '4px', fontSize: '12px' }}>
                    <strong>Latest Answer:</strong> {q.responses[q.responses.length - 1]?.response_text || ''}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: 'var(--color-text-muted)', fontSize: '13px', margin: 0 }}>
            No targeted questions currently attached to this Transfer Pack.
          </p>
        )}
      </div>

      {/* Edit Pack Modal */}
      {showEditModal && (
        <div className={styles.modalBackdrop} onClick={closeEditModal}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0 }}>Edit Transfer Pack</h3>
            {editError && (
              <div style={{ color: 'var(--color-danger, #ef4444)', fontSize: '13px' }}>
                {editError}
              </div>
            )}
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Pack Name</label>
              <input
                type="text"
                className={styles.formInput}
                value={packName}
                onChange={(e) => setPackName(e.target.value)}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Component Area</label>
              <input
                type="text"
                className={styles.formInput}
                value={packArea}
                onChange={(e) => setPackArea(e.target.value)}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Scope Description</label>
              <textarea
                rows={3}
                className={styles.formTextarea}
                value={packDesc}
                onChange={(e) => setPackDesc(e.target.value)}
              />
            </div>
            <div className={styles.modalActions}>
              <button className={styles.actionButton} onClick={closeEditModal}>
                Cancel
              </button>
              <button
                className={`${styles.actionButton} ${styles.primaryBtn}`}
                onClick={() =>
                  updatePackMutation.mutate({
                    name: packName,
                    component_area: packArea,
                    description: packDesc,
                  })
                }
                disabled={updatePackMutation.isPending}
              >
                {updatePackMutation.isPending ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Merge Pack Modal */}
      {showMergeModal && (
        <div className={styles.modalBackdrop} onClick={closeMergeModal}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0 }}>Merge Transfer Pack</h3>
            <p style={{ color: 'var(--color-text-secondary)', fontSize: '13px', margin: 0 }}>
              Select a Transfer Pack to merge into <strong>{pack.name}</strong>. All claims will be consolidated here and the source pack will be deleted.
            </p>
            {mergeError && (
              <div style={{ color: 'var(--color-danger, #ef4444)', fontSize: '13px' }}>
                {mergeError}
              </div>
            )}
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Source Pack to Merge</label>
              <select
                className={styles.formSelect}
                value={sourcePackIdToMerge}
                onChange={(e) => setSourcePackIdToMerge(e.target.value)}
              >
                <option value="">Select a pack...</option>
                {allPacks
                  ?.filter((p) => p.id !== pack.id)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.claims_count ?? (p.claims?.length || 0)} claims)
                    </option>
                  ))}
              </select>
            </div>
            <div className={styles.modalActions}>
              <button className={styles.actionButton} onClick={closeMergeModal}>
                Cancel
              </button>
              <button
                className={`${styles.actionButton} ${styles.primaryBtn}`}
                disabled={!sourcePackIdToMerge || mergePacksMutation.isPending}
                onClick={() => mergePacksMutation.mutate(sourcePackIdToMerge)}
              >
                {mergePacksMutation.isPending ? 'Merging...' : 'Confirm Merge'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Ask Question Modal */}
      {showQuestionModal && (
        <div className={styles.modalBackdrop} onClick={closeQuestionModal}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0 }}>Ask Question for {pack.name}</h3>
            {questionError && (
              <div style={{ color: 'var(--color-danger, #ef4444)', fontSize: '13px' }}>
                {questionError}
              </div>
            )}
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Question Text</label>
              <textarea
                rows={3}
                className={styles.formTextarea}
                placeholder="e.g. What edge cases should the successor know about when upgrading this service?"
                value={qText}
                onChange={(e) => setQText(e.target.value)}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Why It Matters</label>
              <textarea
                rows={2}
                className={styles.formTextarea}
                placeholder="Explain the operational or architectural risk..."
                value={qWhy}
                onChange={(e) => setQWhy(e.target.value)}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Priority</label>
              <select
                className={styles.formSelect}
                value={qPriority}
                onChange={(e) => setQPriority(e.target.value)}
              >
                <option value="CRITICAL">Critical</option>
                <option value="HIGH">High</option>
                <option value="MEDIUM">Medium</option>
                <option value="LOW">Low</option>
              </select>
            </div>
            <div className={styles.modalActions}>
              <button className={styles.actionButton} onClick={closeQuestionModal}>
                Cancel
              </button>
              <button
                className={`${styles.actionButton} ${styles.primaryBtn}`}
                disabled={!qText.trim() || askQuestionMutation.isPending}
                onClick={() =>
                  askQuestionMutation.mutate({
                    case_id: caseId,
                    transfer_pack_id: packId,
                    question_text: qText.trim(),
                    why_it_matters: qWhy.trim() || undefined,
                    priority: qPriority,
                  })
                }
              >
                {askQuestionMutation.isPending ? 'Submitting...' : 'Submit Question'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
