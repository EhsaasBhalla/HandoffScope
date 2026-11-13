import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  FileStack,
  Shield,
  AlertTriangle,
  CheckCircle2,
  Clock,
  ArrowRight,
  GitBranch,
  HelpCircle,
  CheckSquare,
  Share2,
  History,
  Lock,
  Eye,
  ShieldCheck,
  X,
  UserCheck,
  UserPlus,
  Trash2,
  Send,
  Download,
  FileArchive,
  FileCheck,
  Sparkles,
  Layers,
  MessageSquare,
  Plus,
  User,
  FolderKanban,
  XCircle,
  Radio,
} from 'lucide-react';
import { caseApi } from '../../api/case.api';
import { evidenceApi } from '../../api/evidence.api';
import { transferPackApi } from '../../api/transferPack.api';
import { questionApi } from '../../api/question.api';
import { reviewApi } from '../../api/review.api';
import { sharingApi } from '../../api/sharing.api';
import { recipientApi } from '../../api/recipient.api';
import { projectApi } from '../../api/project.api';
import { exportApi } from '../../api/export.api';
import { httpClient } from '../../api/httpClient';
import { ClaimCard } from '../../components/claim-card/claim-card';
import { ApprovalPreflightPanel } from '../../components/approval-preflight-panel/approval-preflight-panel';
import { QuestionThreadCard } from '../../components/question-card/question-card';
import { HandoverChatDrawer } from '../../components/handover-chat-drawer/handover-chat-drawer';
import { useCaseLiveUpdates } from '../../hooks/useCaseLiveUpdates';
import { usePermissions } from '../../hooks/usePermissions';
import styles from './handover-case-detail.module.css';

const STAGES = [
  { id: 'CONNECT', label: 'Connect', statuses: ['DRAFT', 'CONNECTING'] },
  { id: 'RECONSTRUCT', label: 'Reconstruct', statuses: ['INGESTING', 'RECONSTRUCTING'] },
  { id: 'VERIFY', label: 'Verify', statuses: ['NEEDS_INPUT'] },
  { id: 'REVIEW', label: 'Review', statuses: ['UNDER_REVIEW'] },
  { id: 'HANDOVER', label: 'Handover', statuses: ['APPROVED', 'SHARED', 'PARTIALLY_ACKNOWLEDGED', 'ACKNOWLEDGED', 'TRANSFERRED'] },
];

const TABS = [
  { id: 'overview', label: 'Overview', icon: FileStack },
  { id: 'packs', label: 'Transfer Packs', icon: GitBranch },
  { id: 'questions', label: 'Questions', icon: HelpCircle },
  { id: 'review', label: 'Review', icon: CheckSquare },
  { id: 'versions', label: 'Versions', icon: History },
  { id: 'sharing', label: 'Sharing', icon: Share2 },
];

export default function HandoverCaseDetailPage() {
  const { caseId } = useParams();
  const queryClient = useQueryClient();
  const { hasCapability } = usePermissions();

  const canManageCase = hasCapability('case.manage');
  const canTriggerReconstruct = hasCapability('extraction.trigger') || hasCapability('case.manage');
  const canReview = hasCapability('review.submit') || hasCapability('case.approve');
  const canCreateQuestion = hasCapability('question.create');
  const canShare = hasCapability('share.manage');

  const [activeTab, setActiveTab] = useState('overview');
  const [blockReason, setBlockReason] = useState('');
  const [showBlockModal, setShowBlockModal] = useState(false);
  const [blockError, setBlockError] = useState('');

  // Question state
  const [showQuestionModal, setShowQuestionModal] = useState(false);
  const [qText, setQText] = useState('');
  const [qWhy, setQWhy] = useState('');
  const [qPriority, setQPriority] = useState('MEDIUM');
  const [qPackId, setQPackId] = useState('');
  const [questionError, setQuestionError] = useState('');

  // Review & Approval state (Phase 8)
  const [reviewFilter, setReviewFilter] = useState('ALL');
  const [inspectSnapshot, setInspectSnapshot] = useState(null);
  const [reconNotice, setReconNotice] = useState(null);

  // Compliance Export & Verification state (Round 3)
  const [exportBusyKey, setExportBusyKey] = useState('');
  const [exportError, setExportError] = useState('');
  const [verifyResult, setVerifyResult] = useState(null);
  const [verifyBusy, setVerifyBusy] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const { mode: liveMode } = useCaseLiveUpdates(caseId);

  // Sharing & Recipient state (Phase 9)
  const [showShareModal, setShowShareModal] = useState(false);
  const [shareRecipientId, setShareRecipientId] = useState('');
  const [shareVersionId, setShareVersionId] = useState('');
  const [shareError, setShareError] = useState('');
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [assignPackId, setAssignPackId] = useState('');
  const [assignUserId, setAssignUserId] = useState('');
  const [assignError, setAssignError] = useState('');

  // Modal reset handlers
  const closeQuestionModal = () => {
    setShowQuestionModal(false);
    setQText('');
    setQWhy('');
    setQPriority('MEDIUM');
    setQPackId('');
    setQuestionError('');
  };

  const closeBlockModal = () => {
    setShowBlockModal(false);
    setBlockReason('');
    setBlockError('');
  };

  const closeShareModal = () => {
    setShowShareModal(false);
    setShareRecipientId('');
    setShareVersionId('');
    setShareError('');
  };

  const closeAssignModal = () => {
    setShowAssignModal(false);
    setAssignPackId('');
    setAssignUserId('');
    setAssignError('');
  };

  const { data: caseData, isLoading } = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => caseApi.getCase(caseId),
    enabled: !!caseId,
  });

  const { data: packs, isLoading: packsLoading } = useQuery({
    queryKey: ['case-packs', caseId],
    queryFn: () => transferPackApi.listPacks(caseId),
    enabled: !!caseId,
  });

  const { data: caseQuestions, isLoading: questionsLoading } = useQuery({
    queryKey: ['case-questions', caseId],
    queryFn: () => questionApi.listCaseQuestions(caseId),
    enabled: !!caseId,
  });

  // Phase 8 Review & Versions Queries
  const { data: queueSummary } = useQuery({
    queryKey: ['review-queue-summary', caseId],
    queryFn: () => reviewApi.getReviewQueue(caseId),
    enabled: !!caseId,
  });

  const { data: caseClaims, isLoading: claimsLoading } = useQuery({
    queryKey: ['case-claims', caseId],
    queryFn: () => evidenceApi.listClaimsForCase(caseId),
    enabled: !!caseId && (activeTab === 'review' || activeTab === 'overview'),
  });

  const { data: versions } = useQuery({
    queryKey: ['case-versions', caseId],
    queryFn: () => reviewApi.listVersions(caseId),
    enabled: !!caseId,
  });

  const reviewClaimMutation = useMutation({
    mutationFn: ({ claimId, data }) => reviewApi.reviewClaim(claimId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Review action failed');
    },
  });

  const createVersionMutation = useMutation({
    mutationFn: (data) => reviewApi.createVersion(caseId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['case-versions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', caseId] });
      queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
      setActiveTab('versions');
    },
    onError: (err) => {
      alert(err.data?.detail || err.data?.error?.message || err.message || 'Failed to approve version');
    },
  });

  const moveClaimMutation = useMutation({
    mutationFn: ({ claimId, targetPackId }) =>
      transferPackApi.moveClaims(targetPackId, claimId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to move claim');
    },
  });

  const updateClaimMutation = useMutation({
    mutationFn: ({ claimId, data }) => evidenceApi.updateClaim(claimId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to update claim');
    },
  });

  // Phase 9 Sharing & Responsibility Queries
  const { data: caseShares } = useQuery({
    queryKey: ['case-shares', caseId],
    queryFn: () => sharingApi.listCaseShares(caseId),
    enabled: !!caseId && activeTab === 'sharing',
  });

  const { data: caseResponsibilities } = useQuery({
    queryKey: ['case-responsibilities', caseId],
    queryFn: () => recipientApi.listResponsibilities(caseId),
    enabled: !!caseId && activeTab === 'sharing',
  });

  const { data: projectMembers } = useQuery({
    queryKey: ['project-members', caseData?.project_id],
    queryFn: () => projectApi.listProjectMembers(caseData?.project_id),
    enabled: !!caseData?.project_id,
  });

  const shareVersionMutation = useMutation({
    mutationFn: ({ versionId, recipientUserId }) =>
      sharingApi.shareVersion(versionId, recipientUserId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-shares', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
      queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', caseId] });
      closeShareModal();
    },
    onError: (err) => {
      setShareError(err.data?.detail || err.message || 'Failed to issue share grant');
    },
  });

  const revokeShareMutation = useMutation({
    mutationFn: (grantId) => sharingApi.revokeShare(grantId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-shares', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
      queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', caseId] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to revoke share grant');
    },
  });

  const assignResponsibilityMutation = useMutation({
    mutationFn: (data) => recipientApi.assignResponsibility(caseId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-responsibilities', caseId] });
      queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', caseId] });
      queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      closeAssignModal();
    },
    onError: (err) => {
      setAssignError(err.data?.detail || err.message || 'Failed to assign responsibility');
    },
  });

  const createQuestionMutation = useMutation({
    mutationFn: (data) => questionApi.createQuestion(caseId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      closeQuestionModal();
    },
    onError: (err) => {
      setQuestionError(err.data?.detail || err.message || 'Failed to submit question');
    },
  });

  const submitAnswerMutation = useMutation({
    mutationFn: ({ questionId, text }) =>
      questionApi.submitResponse(questionId, { response_text: text }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to submit response');
    },
  });

  const generateAiAnswerMutation = useMutation({
    mutationFn: (questionId) => questionApi.generateAiAnswer(questionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to generate AI response');
    },
  });

  const reviewAnswerMutation = useMutation({
    mutationFn: ({ questionId, ...payload }) =>
      questionApi.reviewResponse(questionId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.data?.error?.message || err.message || 'Review answer failed');
    },
  });

  const transitionQuestionMutation = useMutation({
    mutationFn: ({ questionId, status }) =>
      questionApi.updateQuestion(questionId, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to update question status');
    },
  });

  const reconstructMutation = useMutation({
    mutationFn: () => evidenceApi.triggerReconstruction(caseId),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      setReconNotice(res || null);
      setActiveTab('packs');
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Reconstruction failed');
    },
  });

  const statusMutation = useMutation({
    mutationFn: ({ status, reason }) => caseApi.changeStatus(caseId, status, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to update case status');
    },
  });

  const blockMutation = useMutation({
    mutationFn: ({ blocked, reason }) => caseApi.setBlocked(caseId, blocked, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      closeBlockModal();
    },
    onError: (err) => {
      setBlockError(err.data?.detail || err.message || 'Failed to update case block status');
    },
  });

  if (isLoading) {
    return <div className={styles.loading}>Loading handover case…</div>;
  }

  if (!caseData) {
    return (
      <div className={styles.notFound}>
        <h3>Case not found</h3>
        <Link to="/cases">Back to cases</Link>
      </div>
    );
  }

  // Determine current stage index
  const currentStageIndex = STAGES.findIndex((s) => s.statuses.includes(caseData.status));

  return (
    <div className={styles.container}>
      {/* Blocked Alert Banner if blocked */}
      {caseData.is_blocked && (
        <div className={styles.blockedBanner}>
          <AlertTriangle size={20} className={styles.blockedIcon} />
          <div className={styles.blockedText}>
            <h4>Handover Case Blocked</h4>
            <p>{caseData.blocked_reason || 'This case has been flagged as blocked pending investigation.'}</p>
          </div>
          {canManageCase && (
            <button
              className={styles.unblockBtn}
              onClick={() => blockMutation.mutate({ blocked: false })}
              disabled={blockMutation.isPending}
            >
              Clear Block
            </button>
          )}
        </div>
      )}

      {/* Case Header */}
      <div className={styles.header}>
        <div className={styles.headerInfo}>
          <div className={styles.badgeRow}>
            <span className={styles.caseNumber}>Case #{caseData.case_number}</span>
            <span className={styles.statusBadge}>{caseData.status}</span>
            <span className={styles.syncBadge}>Sync: {caseData.sync_status}</span>
          </div>
          <h2 className={styles.title}>{caseData.title}</h2>
          <p className={styles.desc}>{caseData.description || 'No description provided.'}</p>
        </div>

        <div className={styles.headerActions}>
          <span
            title={liveMode === 'live' ? 'Real-time SSE stream connected' : 'Periodic sync fallback active'}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '5px',
              fontSize: '11px',
              padding: '4px 9px',
              borderRadius: '999px',
              border: '1px solid var(--color-border)',
              color: liveMode === 'live' ? 'var(--color-success)' : 'var(--color-text-muted)',
              backgroundColor: liveMode === 'live' ? 'var(--color-success-bg)' : 'var(--color-bg-secondary)',
            }}
          >
            <Radio size={11} />
            {liveMode === 'live' ? 'Live' : 'Sync'}
          </span>
          <button
            type="button"
            className={styles.btnActionSm}
            style={{ padding: '8px 12px', fontSize: 'var(--text-xs)' }}
            onClick={() => setChatOpen(true)}
          >
            <MessageSquare size={14} /> Ask Handover
          </button>

          {canTriggerReconstruct && (
            <button
              className={styles.primaryActionBtn}
              onClick={() => reconstructMutation.mutate()}
              disabled={reconstructMutation.isPending || caseData.is_blocked}
            >
              <Sparkles size={14} style={{ marginRight: '6px' }} />
              {reconstructMutation.isPending ? 'Reconstructing…' : 'Reconstruct Knowledge'}
            </button>
          )}

          {canManageCase && !caseData.is_blocked ? (
            <button
              className={styles.blockBtn}
              onClick={() => setShowBlockModal(true)}
            >
              Flag as Blocked
            </button>
          ) : null}

          {/* Contextual Status Transition Buttons */}
          {canManageCase && caseData.status === 'DRAFT' && !caseData.is_blocked && (
            <button
              className={styles.primaryActionBtn}
              onClick={() => statusMutation.mutate({ status: 'CONNECTING' })}
              disabled={statusMutation.isPending}
            >
              Start Connection
            </button>
          )}

          {canManageCase && ['RECONSTRUCTING', 'NEEDS_INPUT'].includes(caseData.status) && !caseData.is_blocked && (
            <button
              className={styles.primaryActionBtn}
              onClick={() => statusMutation.mutate({ status: 'UNDER_REVIEW' })}
              disabled={statusMutation.isPending}
            >
              Submit for Review
            </button>
          )}
        </div>
      </div>

      {/* Stage Progress Indicator */}
      <div className={styles.stageIndicator}>
        {STAGES.map((st, idx) => {
          const isComplete = currentStageIndex > idx;
          const isCurrent = currentStageIndex === idx;

          return (
            <div key={st.id} className={styles.stageStep}>
              <div
                className={`${styles.stepCircle} ${
                  isComplete ? styles.stepDone : isCurrent ? styles.stepCurrent : ''
                }`}
              >
                {isComplete ? <CheckCircle2 size={16} /> : idx + 1}
              </div>
              <span className={`${styles.stepLabel} ${isCurrent ? styles.activeStepLabel : ''}`}>
                {st.label}
              </span>
              {idx < STAGES.length - 1 && (
                <div
                  className={`${styles.stepLine} ${
                    isComplete ? styles.stepLineDone : ''
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>

      {reconNotice && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: 'var(--radius-md)',
            marginBottom: 'var(--space-md)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '12px',
            fontSize: 'var(--text-xs)',
            border: `1px solid ${reconNotice.fallback_used || reconNotice.provider_mode !== 'live' ? 'var(--color-warning)' : 'var(--color-success)'}`,
            backgroundColor: reconNotice.fallback_used || reconNotice.provider_mode !== 'live' ? 'var(--color-warning-bg)' : 'var(--color-success-bg)',
            color: 'var(--color-text-primary)',
          }}
        >
          <div>
            <strong>
              {reconNotice.fallback_used
                ? 'Mock Fallback Mode (Live AI Unavailable): '
                : reconNotice.provider_mode === 'mock'
                ? 'Offline Mock Mode (Not Live AI): '
                : `Live AI (${reconNotice.model_used}): `}
            </strong>
            <span>{reconNotice.message}</span>
          </div>
          <button
            className={styles.cancelBtn}
            style={{ padding: '4px 8px', fontSize: '11px' }}
            onClick={() => setReconNotice(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Navigation Tabs */}
      <div className={styles.tabBar}>
        {TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              className={`${styles.tabBtn} ${activeTab === tab.id ? styles.activeTab : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon size={16} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab Content */}
      <div className={styles.tabBody}>
        {activeTab === 'overview' && (
          <div className={styles.overviewTab}>
            <div className={styles.infoCard}>
              <h3>Case Metadata</h3>
              <div className={styles.infoGrid}>
                <div>
                  <span className={styles.infoLabel}>Transition Type</span>
                  <span className={styles.infoValue}>{caseData.transition_type?.replace(/_/g, ' ') || 'STANDARD'}</span>
                </div>
                <div>
                  <span className={styles.infoLabel}>Scope Start</span>
                  <span className={styles.infoValue}>{caseData.scope_start || 'Unbounded'}</span>
                </div>
                <div>
                  <span className={styles.infoLabel}>Scope End</span>
                  <span className={styles.infoValue}>{caseData.scope_end || 'Unbounded'}</span>
                </div>
                <div>
                  <span className={styles.infoLabel}>Created</span>
                  <span className={styles.infoValue}>{caseData.created_at ? new Date(caseData.created_at).toLocaleDateString() : 'N/A'}</span>
                </div>
              </div>
            </div>

            {/* Participants Card */}
            <div className={styles.infoCard}>
              <h3>Participants & Stakeholders</h3>
              <div className={styles.participantsList}>
                {caseData.participants && caseData.participants.length > 0 ? (
                  caseData.participants.map((p) => (
                    <div key={p.id} className={styles.participantItem}>
                      <div className={styles.participantAvatar}>
                        {p.user_display_name ? p.user_display_name[0] : 'U'}
                      </div>
                      <div className={styles.participantInfo}>
                        <h4>{p.user_display_name}</h4>
                        <p>{p.user_email}</p>
                      </div>
                      <span className={styles.roleTag}>{p.role}</span>
                    </div>
                  ))
                ) : (
                  <p className={styles.emptyText}>No participants assigned yet.</p>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'packs' && (
          <div className={styles.packsTab}>
            <div className={styles.packsHeader}>
              <div>
                <h3>Transfer Packs</h3>
                <p className={styles.desc}>
                  Topical workstreams reconstructed from grounded source records and claims.
                </p>
              </div>

              {canTriggerReconstruct && (
                <button
                  className={styles.primaryActionBtn}
                  onClick={() => reconstructMutation.mutate()}
                  disabled={reconstructMutation.isPending || caseData.is_blocked}
                >
                  <Sparkles size={14} style={{ marginRight: '6px' }} />
                  {reconstructMutation.isPending ? 'Reconstructing…' : 'Re-run Extraction'}
                </button>
              )}
            </div>

            {packsLoading ? (
              <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--color-text-muted)' }}>
                Loading Transfer Packs…
              </div>
            ) : packs && packs.length > 0 ? (
              <div className={styles.packsGrid}>
                {packs.map((p) => (
                  <Link
                    key={p.id}
                    to={`/cases/${caseId}/packs/${p.id}`}
                    className={styles.packCard}
                  >
                    <div className={styles.packCardHeader}>
                      <span className={styles.roleTag}>{p.component_area || 'Core Area'}</span>
                      <span className={styles.statusBadge}>{p.status}</span>
                    </div>
                    <h4 className={styles.packName}>{p.name}</h4>
                    <p className={styles.packDescription}>{p.description || 'No description provided.'}</p>
                    <div className={styles.packFooter}>
                      <span>{p.claims_count ?? (p.claims?.length || 0)} Grounded Claims</span>
                      <span style={{ color: 'var(--color-accent)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                        Open Pack <ArrowRight size={12} />
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className={styles.placeholderTab}>
                <Layers size={36} />
                <h3>No Transfer Packs Generated Yet</h3>
                <p>Run AI structured reconstruction to analyze commits, issues, and PRs into grounded workstreams.</p>
                {canTriggerReconstruct && (
                  <button
                    className={styles.primaryActionBtn}
                    onClick={() => reconstructMutation.mutate()}
                    disabled={reconstructMutation.isPending}
                    style={{ marginTop: '1rem' }}
                  >
                    <Sparkles size={14} style={{ marginRight: '6px' }} />
                    {reconstructMutation.isPending ? 'Reconstructing…' : 'Reconstruct Knowledge'}
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {activeTab === 'questions' && (
          <div className={styles.questionsContainer}>
            <div className={styles.packsHeader}>
              <div>
                <h3 style={{ margin: 0, fontSize: 'var(--text-lg)', fontWeight: 'var(--weight-semibold)' }}>
                  Targeted Handover Questions ({caseQuestions?.length || 0})
                </h3>
                <p style={{ margin: '4px 0 0', fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                  Questions directed to the departing contributor to eliminate tribal knowledge gaps.
                </p>
              </div>
              {canCreateQuestion && (
                <button
                  className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                  onClick={() => setShowQuestionModal(true)}
                >
                  <Plus size={14} /> Ask Question
                </button>
              )}
            </div>

            {questionsLoading ? (
              <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--color-text-muted)' }}>
                Loading case questions…
              </div>
            ) : !caseQuestions || caseQuestions.length === 0 ? (
              <div className={styles.placeholderTab}>
                <HelpCircle size={32} />
                <h3>No Questions Asked Yet</h3>
                <p>Add targeted inquiries to clarify runbooks, architectural decisions, and operational subtleties.</p>
                {canCreateQuestion && (
                  <button
                    className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                    style={{ marginTop: 'var(--space-md)' }}
                    onClick={() => setShowQuestionModal(true)}
                  >
                    <Plus size={14} /> Ask First Question
                  </button>
                )}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
                {caseQuestions.map((q) => (
                  <QuestionThreadCard
                    key={q.id}
                    q={q}
                    showCaseTag={false}
                    onSubmitAnswer={(questionId, text) =>
                      submitAnswerMutation.mutateAsync({ questionId, text })
                    }
                    onGenerateAiAnswer={(questionId) =>
                      generateAiAnswerMutation.mutateAsync(questionId)
                    }
                    onReviewResponse={(questionId, payload) =>
                      reviewAnswerMutation.mutateAsync({ questionId, ...payload })
                    }
                    onTransitionStatus={(questionId, status) =>
                      transitionQuestionMutation.mutateAsync({ questionId, status })
                    }
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'review' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
            {/* Review Summary Stats */}
            <div className={styles.reviewStatsGrid}>
              <div className={styles.reviewStatCard}>
                <span className={styles.reviewStatTitle}>Total Claims</span>
                <span className={styles.reviewStatVal}>{queueSummary?.total_claims ?? 0}</span>
              </div>
              <div className={styles.reviewStatCard}>
                <span className={styles.reviewStatTitle}>Pending Review</span>
                <span className={styles.reviewStatVal} style={{ color: 'var(--color-warning)' }}>
                  {queueSummary?.pending_review_count ?? 0}
                </span>
              </div>
              <div className={styles.reviewStatCard}>
                <span className={styles.reviewStatTitle}>Accepted</span>
                <span className={styles.reviewStatVal} style={{ color: 'var(--color-success)' }}>
                  {(queueSummary?.accepted_count || 0) + (queueSummary?.edited_and_accepted_count || 0)}
                </span>
              </div>
              <div className={styles.reviewStatCard}>
                <span className={styles.reviewStatTitle}>Clarifications</span>
                <span className={styles.reviewStatVal} style={{ color: 'var(--color-info)' }}>
                  {queueSummary?.needs_clarification_count ?? 0}
                </span>
              </div>
              <div className={styles.reviewStatCard}>
                <span className={styles.reviewStatTitle}>Rejected</span>
                <span className={styles.reviewStatVal} style={{ color: 'var(--color-error)' }}>
                  {queueSummary?.rejected_count ?? 0}
                </span>
              </div>
              <div className={styles.reviewStatCard}>
                <span className={styles.reviewStatTitle}>Open Questions</span>
                <span
                  className={styles.reviewStatVal}
                  style={{
                    color: (queueSummary?.open_questions_count || 0) + (queueSummary?.awaiting_question_review_count || 0) > 0 ? 'var(--color-warning)' : 'var(--color-success)',
                  }}
                >
                  {(queueSummary?.open_questions_count || 0) + (queueSummary?.awaiting_question_review_count || 0)}
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

            {/* Filter Chips */}
            <div className={styles.filterChipsRow}>
              {[
                { id: 'ALL', label: 'All Claims' },
                { id: 'PENDING_REVIEW', label: 'Pending Review' },
                { id: 'ACCEPTED', label: 'Accepted' },
                { id: 'EDITED_AND_ACCEPTED', label: 'Edited & Accepted' },
                { id: 'NEEDS_CLARIFICATION', label: 'Needs Clarification' },
                { id: 'REJECTED', label: 'Rejected' },
              ].map((f) => (
                <button
                  key={f.id}
                  className={`${styles.filterChip} ${reviewFilter === f.id ? styles.filterChipActive : ''}`}
                  onClick={() => setReviewFilter(f.id)}
                >
                  {f.label}
                </button>
              ))}
            </div>

            {/* Claims Review List */}
            {claimsLoading ? (
              <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--color-text-muted)' }}>
                Loading claims for review…
              </div>
            ) : !caseClaims || caseClaims.length === 0 ? (
              <div className={styles.placeholderTab}>
                <Layers size={32} />
                <h3>No Claims Found</h3>
                <p>Run reconstruction or add transfer packs to start generating claims.</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
                {caseClaims
                  .filter((c) => reviewFilter === 'ALL' || c.review_state === reviewFilter)
                  .map((claim) => (
                    <ClaimCard
                      key={claim.id}
                      claim={claim}
                      availablePacks={packs || []}
                      enableReview={canReview}
                      onReviewClaim={(claimId, data) => reviewClaimMutation.mutateAsync({ claimId, data })}
                      onUpdateClaim={(claimId, data) => updateClaimMutation.mutateAsync({ claimId, data })}
                      onMoveClaim={(claimId, targetPackId) => moveClaimMutation.mutateAsync({ claimId, targetPackId })}
                    />
                  ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'versions' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 'var(--text-lg)', fontWeight: 'var(--weight-semibold)' }}>
                  Approved Version History ({versions?.length || 0})
                </h3>
                <p style={{ margin: '4px 0 0', fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                  Immutable snapshots capturing approved handover state with tamper-evident PDF and signed archive exports.
                </p>
              </div>
              <label
                className={styles.btnActionSm}
                style={{ cursor: verifyBusy ? 'wait' : 'pointer', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
              >
                <FileCheck size={13} />
                {verifyBusy ? 'Verifying Archive…' : 'Verify Compliance Bundle (.zip)'}
                <input
                  type="file"
                  accept=".zip,application/zip"
                  style={{ display: 'none' }}
                  disabled={verifyBusy}
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    e.target.value = '';
                    if (!file) return;
                    setExportError('');
                    setVerifyBusy(true);
                    try {
                      const res = await exportApi.verifyBundle(file);
                      setVerifyResult(res);
                    } catch (err) {
                      setExportError(err.message || 'Archive verification failed.');
                    } finally {
                      setVerifyBusy(false);
                    }
                  }}
                />
              </label>
            </div>

            {exportError && (
              <div style={{ padding: '10px 12px', borderRadius: '6px', backgroundColor: 'var(--color-error-bg)', border: '1px solid var(--color-error)', color: 'var(--color-error)', fontSize: '12px' }}>
                {exportError}
              </div>
            )}

            {verifyResult && (
              <div
                style={{
                  padding: '12px 14px',
                  borderRadius: '8px',
                  backgroundColor: verifyResult.overall_status === 'VALID' ? 'var(--color-success-bg)' : 'var(--color-error-bg)',
                  border: `1px solid ${verifyResult.overall_status === 'VALID' ? 'var(--color-success)' : 'var(--color-error)'}`,
                  fontSize: '12px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <strong>Verification Outcome: {verifyResult.overall_status}</strong>
                  <button type="button" onClick={() => setVerifyResult(null)} style={{ color: 'inherit' }}>
                    <X size={14} />
                  </button>
                </div>
                <div>
                  Integrity: {verifyResult.integrity_valid ? 'Valid' : 'Failed'} • Signature: {verifyResult.signature_valid ? 'Ed25519 Valid' : 'Invalid'} • Trusted Signer: {verifyResult.trusted_signer_verified ? 'Verified' : 'Unverified'} ({verifyResult.artifacts_checked} artifacts checked)
                </div>
                {verifyResult.public_key_fingerprint && (
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                    Fingerprint: {verifyResult.public_key_fingerprint}
                  </div>
                )}
                {verifyResult.errors?.length > 0 && (
                  <div style={{ color: 'var(--color-error)' }}>{verifyResult.errors.join(' | ')}</div>
                )}
              </div>
            )}

            {!versions || versions.length === 0 ? (
              <div className={styles.placeholderTab}>
                <ShieldCheck size={32} />
                <h3>No Approved Versions Yet</h3>
                <p>Complete the review queue and approve all claims to freeze version 1.</p>
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
                        <span>{v.approved_at ? new Date(v.approved_at).toLocaleString() : 'N/A'}</span>
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

                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                      <button
                        className={styles.btnActionSm}
                        onClick={async () => {
                          try {
                            const detail = await reviewApi.getVersion(v.id);
                            setInspectSnapshot(detail);
                          } catch (err) {
                            alert(err.data?.detail || err.message || 'Failed to fetch version snapshot');
                          }
                        }}
                      >
                        <Eye size={12} /> View Frozen Snapshot JSON
                      </button>
                      <button
                        className={styles.btnActionSm}
                        disabled={exportBusyKey === `pdf-${v.version_number}`}
                        onClick={async () => {
                          setExportError('');
                          setExportBusyKey(`pdf-${v.version_number}`);
                          try {
                            await exportApi.downloadCertificatePdf(caseId, v.version_number);
                          } catch (err) {
                            setExportError(err.message || 'Failed to download PDF certificate.');
                          } finally {
                            setExportBusyKey('');
                          }
                        }}
                      >
                        <Download size={12} />
                        {exportBusyKey === `pdf-${v.version_number}` ? 'Generating PDF…' : 'Certificate PDF'}
                      </button>
                      <button
                        className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                        disabled={exportBusyKey === `zip-${v.version_number}`}
                        onClick={async () => {
                          setExportError('');
                          setExportBusyKey(`zip-${v.version_number}`);
                          try {
                            await exportApi.downloadComplianceBundle(caseId, v.version_number);
                          } catch (err) {
                            setExportError(err.message || 'Failed to export compliance bundle.');
                          } finally {
                            setExportBusyKey('');
                          }
                        }}
                      >
                        <FileArchive size={12} />
                        {exportBusyKey === `zip-${v.version_number}` ? 'Packaging ZIP…' : 'Signed Compliance Bundle (.zip)'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'sharing' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-xl)' }}>
            {/* 1. Share Grants Section */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: 'var(--text-lg)', fontWeight: 'var(--weight-semibold)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Share2 size={18} style={{ color: 'var(--color-accent)' }} />
                    Version Share Grants ({caseShares?.length || 0})
                  </h3>
                  <p style={{ margin: '4px 0 0', fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                    Grant verified successors and incoming leads read/sign-off access to approved version snapshots.
                  </p>
                </div>
                {canShare && (
                  <button
                    className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                    onClick={() => setShowShareModal(true)}
                    disabled={!versions || versions.length === 0}
                  >
                    <Send size={14} /> Share Version Access
                  </button>
                )}
              </div>

              {!caseShares || caseShares.length === 0 ? (
                <div className={styles.placeholderTab} style={{ padding: '2rem' }}>
                  <UserPlus size={32} />
                  <h3>No Active Share Grants</h3>
                  <p>Approve a version and issue a share grant to allow successors to review and acknowledge this handover.</p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                  {caseShares.map((g) => (
                    <div key={g.id} className={styles.versionCard}>
                      <div className={styles.versionTop}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)', color: 'var(--color-text-primary)' }}>
                            {g.recipient_name}
                          </span>
                          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                            ({g.recipient_email})
                          </span>
                          <span className={g.is_active ? styles.currentPill : styles.supersededPill}>
                            {g.is_active ? 'Active Grant' : 'Revoked'}
                          </span>
                          {g.is_acknowledged ? (
                            <span className={styles.currentPill}>Acknowledged</span>
                          ) : (
                            <span className={styles.supersededPill}>Pending Ack</span>
                          )}
                        </div>

                        {canShare && g.is_active && (
                          <button
                            className={styles.btnActionSm}
                            onClick={() => revokeShareMutation.mutate(g.id)}
                            style={{ color: 'var(--color-error)' }}
                          >
                            <Trash2 size={12} /> Revoke Access
                          </button>
                        )}
                      </div>

                      <div className={styles.versionMeta}>
                        <span>Version {g.version_number}</span>
                        <span>•</span>
                        <span>Granted {g.granted_at ? new Date(g.granted_at).toLocaleDateString() : 'N/A'} by {g.granter_name || 'Lead'}</span>
                        {g.acknowledged_at && (
                          <>
                            <span>•</span>
                            <span>Acknowledged {new Date(g.acknowledged_at).toLocaleString()}</span>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* 2. Responsibility Assignments Section */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: 'var(--text-lg)', fontWeight: 'var(--weight-semibold)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <UserCheck size={18} style={{ color: 'var(--color-accent)' }} />
                    Transfer Pack Responsibility Assignments ({caseResponsibilities?.length || 0})
                  </h3>
                  <p style={{ margin: '4px 0 0', fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                    Map operational ownership of specific services and runbooks to incoming engineers.
                  </p>
                </div>
                {canShare && (
                  <button
                    className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                    onClick={() => setShowAssignModal(true)}
                    disabled={!packs || packs.length === 0}
                  >
                    <UserPlus size={14} /> Assign Pack Ownership
                  </button>
                )}
              </div>

              {!caseResponsibilities || caseResponsibilities.length === 0 ? (
                <div className={styles.placeholderTab} style={{ padding: '2rem' }}>
                  <Layers size={32} />
                  <h3>No Responsibilities Assigned Yet</h3>
                  <p>Assign transfer packs to specific engineers to initiate the formal acceptance workflow.</p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                  {caseResponsibilities.map((r) => {
                    const isAccepted = r.status === 'ACCEPTED';
                    const isDeclined = r.status === 'DECLINED';

                    return (
                      <div key={r.id} className={styles.versionCard}>
                        <div className={styles.versionTop}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)', color: 'var(--color-text-primary)' }}>
                              {r.transfer_pack_name}
                            </span>
                            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                              ({r.transfer_pack_area || 'Core'})
                            </span>
                            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-accent-text)' }}>
                              → Assigned to {r.assignee_name}
                            </span>
                          </div>

                          <span
                            className={styles.supersededPill}
                            style={{
                              color: isAccepted ? 'var(--color-success)' : isDeclined ? 'var(--color-error)' : 'var(--color-warning)',
                              borderColor: isAccepted ? 'var(--color-success)' : isDeclined ? 'var(--color-error)' : 'var(--color-warning)',
                            }}
                          >
                            {(r.status || '').replace(/_/g, ' ')}
                          </span>
                        </div>

                        <div className={styles.versionMeta}>
                          <span>Assigned {r.assigned_at ? new Date(r.assigned_at).toLocaleDateString() : 'N/A'}</span>
                          {r.responded_at && (
                            <>
                              <span>•</span>
                              <span>Responded {new Date(r.responded_at).toLocaleString()}</span>
                            </>
                          )}
                        </div>

                        {r.decline_reason && (
                          <div className={styles.versionReason} style={{ borderLeftColor: 'var(--color-error)', color: 'var(--color-error)' }}>
                            <strong>Decline Reason:</strong> {r.decline_reason}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Ask Question Modal */}
      {showQuestionModal && (
        <div className={styles.modalOverlay} onClick={closeQuestionModal}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0 }}>Ask a Handover Question</h3>
            <p className={styles.modalSubtitle}>
              Target an inquiry to uncover hidden assumptions and unwritten practices.
            </p>

            {questionError && (
              <div style={{ fontSize: '12px', color: 'var(--color-error)', padding: '6px 8px', borderRadius: '4px', backgroundColor: 'var(--color-error-bg)' }}>
                {questionError}
              </div>
            )}

            {packs && packs.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                  Linked Transfer Pack (Optional)
                </label>
                <select
                  value={qPackId}
                  onChange={(e) => setQPackId(e.target.value)}
                  style={{
                    padding: '8px',
                    backgroundColor: 'var(--color-bg-primary)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--color-text-primary)',
                    fontSize: '13px',
                  }}
                >
                  <option value="">General (Case-wide knowledge gap)</option>
                  {packs.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>Question</label>
              <textarea
                rows={3}
                placeholder="e.g. What is the procedure for updating production encryption keys?"
                value={qText}
                onChange={(e) => setQText(e.target.value)}
                style={{
                  padding: '8px',
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--color-text-primary)',
                  fontSize: '13px',
                }}
              />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                Why It Matters (Operational Context)
              </label>
              <textarea
                rows={2}
                placeholder="Explain the impact or risk..."
                value={qWhy}
                onChange={(e) => setQWhy(e.target.value)}
                style={{
                  padding: '8px',
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--color-text-primary)',
                  fontSize: '12px',
                }}
              />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>Priority</label>
              <select
                value={qPriority}
                onChange={(e) => setQPriority(e.target.value)}
                style={{
                  padding: '8px',
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--color-text-primary)',
                  fontSize: '13px',
                }}
              >
                <option value="CRITICAL">Critical (Immediate Operational Risk)</option>
                <option value="HIGH">High (Key Architecture Decision)</option>
                <option value="MEDIUM">Medium (General Knowledge Transfer)</option>
                <option value="LOW">Low (Minor Documentation Detail)</option>
              </select>
            </div>

            <div className={styles.modalActions}>
              <button className={styles.cancelBtn} onClick={closeQuestionModal}>
                Cancel
              </button>
              <button
                className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                style={{ padding: '8px 16px', fontSize: '13px' }}
                disabled={!qText.trim() || createQuestionMutation.isPending}
                onClick={() =>
                  createQuestionMutation.mutate({
                    case_id: caseId,
                    transfer_pack_id: qPackId || undefined,
                    question_text: qText.trim(),
                    why_it_matters: qWhy.trim() || undefined,
                    priority: qPriority,
                  })
                }
              >
                {createQuestionMutation.isPending ? 'Submitting...' : 'Submit Question'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Block Modal */}
      {showBlockModal && (
        <div className={styles.modalOverlay} onClick={closeBlockModal}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3>Flag Case as Blocked</h3>
            <p className={styles.modalSubtitle}>Provide a reason for blocking this handover case.</p>
            {blockError && (
              <div style={{ fontSize: '12px', color: 'var(--color-error)', padding: '6px 8px', borderRadius: '4px', backgroundColor: 'var(--color-error-bg)' }}>
                {blockError}
              </div>
            )}
            <textarea
              rows={3}
              placeholder="e.g. Missing key architectural documentation from vendor, pending security audit..."
              value={blockReason}
              onChange={(e) => setBlockReason(e.target.value)}
            />
            <div className={styles.modalActions}>
              <button className={styles.cancelBtn} onClick={closeBlockModal}>
                Cancel
              </button>
              <button
                className={styles.confirmBlockBtn}
                onClick={() => blockMutation.mutate({ blocked: true, reason: blockReason })}
                disabled={blockMutation.isPending}
              >
                {blockMutation.isPending ? 'Blocking…' : 'Block Case'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Snapshot Inspection Modal */}
      {inspectSnapshot && (
        <div className={styles.modalOverlay} onClick={() => setInspectSnapshot(null)}>
          <div className={styles.modal} style={{ maxWidth: '800px' }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0 }}>Frozen Snapshot — Version {inspectSnapshot.version_number}</h3>
              <button className={styles.cancelBtn} onClick={() => setInspectSnapshot(null)}>
                <X size={16} />
              </button>
            </div>
            <p className={styles.modalSubtitle}>
              Approved {inspectSnapshot.approved_at ? new Date(inspectSnapshot.approved_at).toLocaleString() : 'N/A'} by {inspectSnapshot.approved_by_name || 'Reviewer'}
            </p>
            <pre className={styles.jsonViewer}>
              {JSON.stringify(inspectSnapshot.snapshot_json || {}, null, 2)}
            </pre>
            <div className={styles.modalActions}>
              <button
                className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                onClick={() => setInspectSnapshot(null)}
              >
                Close Snapshot
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Share Version Modal (Phase 9) */}
      {showShareModal && (
        <div className={styles.modalOverlay} onClick={closeShareModal}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0 }}>Share Approved Version</h3>
            <p className={styles.modalSubtitle}>
              Grant an incoming successor or stakeholder read and acknowledgment access to an approved version snapshot.
            </p>

            {shareError && (
              <div style={{ fontSize: '12px', color: 'var(--color-error)', padding: '6px 8px', borderRadius: '4px', backgroundColor: 'var(--color-error-bg)' }}>
                {shareError}
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                Target Handover Version
              </label>
              <select
                value={shareVersionId || versions?.[0]?.id || ''}
                onChange={(e) => setShareVersionId(e.target.value)}
                style={{
                  padding: '8px',
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--color-text-primary)',
                  fontSize: '13px',
                }}
              >
                {(versions || []).map((v) => (
                  <option key={v.id} value={v.id}>
                    Version {v.version_number} {v.is_current ? '(Current Active)' : '(Superseded)'}
                  </option>
                ))}
              </select>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                Select Recipient / Successor
              </label>
              <select
                value={shareRecipientId}
                onChange={(e) => setShareRecipientId(e.target.value)}
                style={{
                  padding: '8px',
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--color-text-primary)',
                  fontSize: '13px',
                }}
              >
                <option value="">Choose a team member...</option>
                {(projectMembers || []).map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.user_display_name || m.name || m.user_email || m.email} ({m.role})
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.modalActions}>
              <button className={styles.cancelBtn} onClick={closeShareModal}>
                Cancel
              </button>
              <button
                className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                style={{ padding: '8px 16px', fontSize: '13px' }}
                disabled={!shareRecipientId || !(versions && versions.length > 0) || shareVersionMutation.isPending}
                onClick={() =>
                  shareVersionMutation.mutate({
                    versionId: shareVersionId || versions?.[0]?.id,
                    recipientUserId: shareRecipientId,
                  })
                }
              >
                <Send size={14} />
                {shareVersionMutation.isPending ? 'Issuing Grant…' : 'Issue Share Grant'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Assign Pack Responsibility Modal (Phase 9) */}
      {showAssignModal && (
        <div className={styles.modalOverlay} onClick={closeAssignModal}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0 }}>Assign Transfer Pack Responsibility</h3>
            <p className={styles.modalSubtitle}>
              Designate a successor as the operational owner for this Transfer Pack.
            </p>

            {assignError && (
              <div style={{ fontSize: '12px', color: 'var(--color-error)', padding: '6px 8px', borderRadius: '4px', backgroundColor: 'var(--color-error-bg)' }}>
                {assignError}
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                Transfer Pack
              </label>
              <select
                value={assignPackId || packs?.[0]?.id || ''}
                onChange={(e) => setAssignPackId(e.target.value)}
                style={{
                  padding: '8px',
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--color-text-primary)',
                  fontSize: '13px',
                }}
              >
                {(packs || []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.component_area || 'Core'})
                  </option>
                ))}
              </select>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                Designated Successor
              </label>
              <select
                value={assignUserId}
                onChange={(e) => setAssignUserId(e.target.value)}
                style={{
                  padding: '8px',
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--color-text-primary)',
                  fontSize: '13px',
                }}
              >
                <option value="">Select successor engineer...</option>
                {(projectMembers || []).map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.user_display_name || m.name || m.user_email || m.email} ({m.role})
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.modalActions}>
              <button className={styles.cancelBtn} onClick={closeAssignModal}>
                Cancel
              </button>
              <button
                className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                style={{ padding: '8px 16px', fontSize: '13px' }}
                disabled={!assignUserId || !(packs && packs.length > 0) || assignResponsibilityMutation.isPending}
                onClick={() =>
                  assignResponsibilityMutation.mutate({
                    transfer_pack_id: assignPackId || packs?.[0]?.id,
                    assigned_user_id: assignUserId,
                    handover_version_id: versions?.[0]?.id,
                  })
                }
              >
                <UserPlus size={14} />
                {assignResponsibilityMutation.isPending ? 'Assigning…' : 'Confirm Assignment'}
              </button>
            </div>
          </div>
        </div>
      )}

      <HandoverChatDrawer
        isOpen={chatOpen}
        onClose={() => setChatOpen(false)}
        caseId={caseId}
        hasApprovedVersion={Boolean(versions && versions.length > 0)}
        approvedVersionNumber={versions?.[0]?.version_number || null}
        isRecipientOnly={false}
      />
    </div>
  );
}
