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
} from 'lucide-react';
import { caseApi } from '../../api/case.api';
import { evidenceApi } from '../../api/evidence.api';
import { transferPackApi } from '../../api/transferPack.api';
import { questionApi } from '../../api/question.api';
import { reviewApi } from '../../api/review.api';
import { ClaimCard } from '../../components/claim-card/claim-card';
import { Sparkles, Layers, MessageSquare, Plus, User, FolderKanban, XCircle } from 'lucide-react';
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
  const [activeTab, setActiveTab] = useState('overview');
  const [blockReason, setBlockReason] = useState('');
  const [showBlockModal, setShowBlockModal] = useState(false);

  // Question state
  const [showQuestionModal, setShowQuestionModal] = useState(false);
  const [qText, setQText] = useState('');
  const [qWhy, setQWhy] = useState('');
  const [qPriority, setQPriority] = useState('MEDIUM');
  const [qPackId, setQPackId] = useState('');
  const [answeringQId, setAnsweringQId] = useState(null);
  const [ansText, setAnsText] = useState('');

  // Review & Approval state (Phase 8)
  const [reviewFilter, setReviewFilter] = useState('ALL');
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [amendmentReason, setAmendmentReason] = useState('');
  const [inspectSnapshot, setInspectSnapshot] = useState(null);

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
    enabled: !!caseId && (activeTab === 'versions' || activeTab === 'review'),
  });

  const reviewClaimMutation = useMutation({
    mutationFn: ({ claimId, data }) => reviewApi.reviewClaim(claimId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
    },
  });

  const createVersionMutation = useMutation({
    mutationFn: (data) => reviewApi.createVersion(caseId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-versions', caseId] });
      queryClient.invalidateQueries({ queryKey: ['review-queue-summary', caseId] });
      setShowApproveModal(false);
      setAmendmentReason('');
      setActiveTab('versions');
    },
  });

  const moveClaimMutation = useMutation({
    mutationFn: ({ claimId, targetPackId }) =>
      transferPackApi.moveClaims(targetPackId, claimId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
    },
  });

  const updateClaimMutation = useMutation({
    mutationFn: ({ claimId, data }) => evidenceApi.updateClaim(claimId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-claims', caseId] });
    },
  });

  const createQuestionMutation = useMutation({
    mutationFn: (data) => questionApi.createQuestion(caseId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      setShowQuestionModal(false);
      setQText('');
      setQWhy('');
      setQPackId('');
    },
  });

  const submitAnswerMutation = useMutation({
    mutationFn: ({ questionId, text }) =>
      questionApi.submitResponse(questionId, { response_text: text }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
      setAnsweringQId(null);
      setAnsText('');
    },
  });

  const reviewAnswerMutation = useMutation({
    mutationFn: ({ questionId, action }) =>
      questionApi.reviewResponse(questionId, { action }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-questions', caseId] });
    },
  });

  const reconstructMutation = useMutation({
    mutationFn: () => evidenceApi.triggerReconstruction(caseId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case-packs', caseId] });
      setActiveTab('packs');
    },
  });

  const statusMutation = useMutation({
    mutationFn: ({ status, reason }) => caseApi.changeStatus(caseId, status, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
    },
  });

  const blockMutation = useMutation({
    mutationFn: ({ blocked, reason }) => caseApi.setBlocked(caseId, blocked, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      setShowBlockModal(false);
      setBlockReason('');
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
          <button
            className={styles.unblockBtn}
            onClick={() => blockMutation.mutate({ blocked: false })}
            disabled={blockMutation.isPending}
          >
            Clear Block
          </button>
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
          <button
            className={styles.primaryActionBtn}
            onClick={() => reconstructMutation.mutate()}
            disabled={reconstructMutation.isPending || caseData.is_blocked}
          >
            <Sparkles size={14} style={{ marginRight: '6px' }} />
            {reconstructMutation.isPending ? 'Reconstructing…' : 'Reconstruct Knowledge'}
          </button>

          {!caseData.is_blocked ? (
            <button
              className={styles.blockBtn}
              onClick={() => setShowBlockModal(true)}
            >
              Flag as Blocked
            </button>
          ) : null}

          {/* Contextual Status Transition Buttons */}
          {caseData.status === 'DRAFT' && !caseData.is_blocked && (
            <button
              className={styles.primaryActionBtn}
              onClick={() => statusMutation.mutate({ status: 'CONNECTING' })}
              disabled={statusMutation.isPending}
            >
              Start Connection
            </button>
          )}

          {caseData.status === 'RECONSTRUCTING' && !caseData.is_blocked && (
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
                  <span className={styles.infoValue}>{caseData.transition_type.replace(/_/g, ' ')}</span>
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
                  <span className={styles.infoValue}>{new Date(caseData.created_at).toLocaleDateString()}</span>
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

              <button
                className={styles.primaryActionBtn}
                onClick={() => reconstructMutation.mutate()}
                disabled={reconstructMutation.isPending || caseData.is_blocked}
              >
                <Sparkles size={14} style={{ marginRight: '6px' }} />
                {reconstructMutation.isPending ? 'Reconstructing…' : 'Re-run Extraction'}
              </button>
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
                      <span>{p.claims_count} Grounded Claims</span>
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
                <button
                  className={styles.primaryActionBtn}
                  onClick={() => reconstructMutation.mutate()}
                  disabled={reconstructMutation.isPending}
                  style={{ marginTop: '1rem' }}
                >
                  <Sparkles size={14} style={{ marginRight: '6px' }} />
                  {reconstructMutation.isPending ? 'Reconstructing…' : 'Reconstruct Knowledge'}
                </button>
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
              <button
                className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                onClick={() => setShowQuestionModal(true)}
              >
                <Plus size={14} /> Ask Question
              </button>
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
                <button
                  className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                  style={{ marginTop: 'var(--space-md)' }}
                  onClick={() => setShowQuestionModal(true)}
                >
                  <Plus size={14} /> Ask First Question
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
                {caseQuestions.map((q) => {
                  const statusUpper = (q.status || '').toUpperCase();
                  const isAnswering = answeringQId === q.id;

                  return (
                    <div key={q.id} className={styles.caseQuestionCard}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '8px' }}>
                        <div className={styles.qBadgeRow}>
                          <span
                            className={`${styles.qBadge} ${
                              statusUpper === 'OPEN'
                                ? styles.qBadgeOpen
                                : statusUpper === 'ANSWERED'
                                ? styles.qBadgeAnswered
                                : styles.qBadgeResolved
                            }`}
                          >
                            {q.status}
                          </span>
                          <span
                            className={`${styles.qPriorityBadge} ${
                              q.priority === 'CRITICAL'
                                ? styles.qPriorityCritical
                                : q.priority === 'HIGH'
                                ? styles.qPriorityHigh
                                : ''
                            }`}
                          >
                            {q.priority}
                          </span>
                          {q.transfer_pack_name && (
                            <span className={styles.qPriorityBadge} style={{ color: 'var(--color-accent)' }}>
                              <FolderKanban size={11} style={{ display: 'inline', marginRight: 3, verticalAlign: 'middle' }} />
                              {q.transfer_pack_name}
                            </span>
                          )}
                        </div>
                        <span style={{ fontSize: '11px', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
                          {new Date(q.created_at).toLocaleDateString()}
                        </span>
                      </div>

                      <h4 style={{ margin: 0, fontSize: '15px', color: 'var(--color-text-primary)' }}>
                        {q.question_text}
                      </h4>

                      {q.why_it_matters && (
                        <div style={{ backgroundColor: 'var(--color-bg-primary)', padding: '8px 12px', borderRadius: '4px', borderLeft: '3px solid var(--color-accent)', fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                          <strong>Why this matters:</strong> {q.why_it_matters}
                        </div>
                      )}

                      {/* Responses thread */}
                      {q.responses && q.responses.length > 0 && (
                        <div className={styles.responseThread}>
                          {q.responses.map((resp) => (
                            <div key={resp.id} className={styles.responseItem}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span style={{ fontWeight: 600, fontSize: '12px' }}>
                                  Answer by {resp.respondent_name || 'Respondent'}:
                                </span>
                                <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: resp.review_state === 'ACCEPTED' ? '#34d399' : '#fbbf24' }}>
                                  {resp.review_state}
                                </span>
                              </div>
                              <p style={{ margin: '4px 0 0', lineHeight: 1.5 }}>{resp.response_text}</p>
                              {resp.review_notes && (
                                <p style={{ margin: '4px 0 0', fontSize: '11px', color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                                  Review note: {resp.review_notes}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Inline Answering Box */}
                      {isAnswering && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '8px' }}>
                          <textarea
                            rows={3}
                            placeholder="Write your answer..."
                            value={ansText}
                            onChange={(e) => setAnsText(e.target.value)}
                            style={{
                              padding: '8px',
                              backgroundColor: 'var(--color-bg-primary)',
                              border: '1px solid var(--color-border)',
                              borderRadius: '4px',
                              color: 'var(--color-text-primary)',
                              fontSize: '13px',
                            }}
                          />
                          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                            <button
                              className={styles.btnActionSm}
                              onClick={() => {
                                setAnsweringQId(null);
                                setAnsText('');
                              }}
                            >
                              Cancel
                            </button>
                            <button
                              className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                              disabled={submitAnswerMutation.isPending || !ansText.trim()}
                              onClick={() => submitAnswerMutation.mutate({ questionId: q.id, text: ansText.trim() })}
                            >
                              {submitAnswerMutation.isPending ? 'Submitting...' : 'Submit Answer'}
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Action buttons */}
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', paddingTop: '4px' }}>
                        {!isAnswering && statusUpper !== 'RESOLVED' && statusUpper !== 'DISMISSED' && (
                          <button
                            className={styles.btnActionSm}
                            onClick={() => setAnsweringQId(q.id)}
                          >
                            <MessageSquare size={12} />
                            {q.responses?.length > 0 ? 'Add Follow-up Answer' : 'Answer Question'}
                          </button>
                        )}

                        {statusUpper === 'ANSWERED' && q.responses?.length > 0 && (
                          <>
                            <button
                              className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                              onClick={() => reviewAnswerMutation.mutate({ questionId: q.id, action: 'accept' })}
                            >
                              <CheckCircle2 size={12} /> Accept Answer
                            </button>
                            <button
                              className={styles.btnActionSm}
                              onClick={() => reviewAnswerMutation.mutate({ questionId: q.id, action: 'reject' })}
                            >
                              <XCircle size={12} /> Request Revision
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
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
                <span className={styles.reviewStatVal} style={{ color: '#fbbf24' }}>
                  {queueSummary?.pending_review_count ?? 0}
                </span>
              </div>
              <div className={styles.reviewStatCard}>
                <span className={styles.reviewStatTitle}>Accepted</span>
                <span className={styles.reviewStatVal} style={{ color: '#34d399' }}>
                  {(queueSummary?.accepted_count || 0) + (queueSummary?.edited_and_accepted_count || 0)}
                </span>
              </div>
              <div className={styles.reviewStatCard}>
                <span className={styles.reviewStatTitle}>Clarifications</span>
                <span className={styles.reviewStatVal} style={{ color: '#60a5fa' }}>
                  {queueSummary?.needs_clarification_count ?? 0}
                </span>
              </div>
              <div className={styles.reviewStatCard}>
                <span className={styles.reviewStatTitle}>Rejected</span>
                <span className={styles.reviewStatVal} style={{ color: '#f87171' }}>
                  {queueSummary?.rejected_count ?? 0}
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
                    <CheckCircle2 size={22} style={{ color: '#34d399', flexShrink: 0, marginTop: '2px' }} />
                  ) : (
                    <AlertTriangle size={22} style={{ color: '#fbbf24', flexShrink: 0, marginTop: '2px' }} />
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
                        {queueSummary.blocking_reasons.map((r, i) => (
                          <li key={i}>{r}</li>
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
                  <ShieldCheck size={14} /> Approve Version Snapshot
                </button>
              </div>
            )}

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
                      enableReview={true}
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
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 'var(--text-lg)', fontWeight: 'var(--weight-semibold)' }}>
                  Approved Version History ({versions?.length || 0})
                </h3>
                <p style={{ margin: '4px 0 0', fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                  Immutable audit snapshots capturing the verified state of all knowledge areas and claims.
                </p>
              </div>
            </div>

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

                    <div>
                      <button
                        className={styles.btnActionSm}
                        onClick={async () => {
                          const detail = await reviewApi.getVersion(v.id);
                          setInspectSnapshot(detail);
                        }}
                      >
                        <Eye size={12} /> View Frozen Snapshot JSON
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'sharing' && (
          <div className={styles.placeholderTab}>
            <Share2 size={32} />
            <h3>Recipients & Access Sharing</h3>
            <p>Share grants and successor projections will appear here (Phase 9).</p>
          </div>
        )}
      </div>

      {/* Ask Question Modal */}
      {showQuestionModal && (
        <div className={styles.modalOverlay} onClick={() => setShowQuestionModal(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0 }}>Ask a Handover Question</h3>
            <p className={styles.modalSubtitle}>
              Target an inquiry to uncover hidden assumptions and unwritten practices.
            </p>

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
              <button className={styles.cancelBtn} onClick={() => setShowQuestionModal(false)}>
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
        <div className={styles.modalOverlay} onClick={() => setShowBlockModal(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3>Flag Case as Blocked</h3>
            <p className={styles.modalSubtitle}>Provide a reason for blocking this handover case.</p>
            <textarea
              rows={3}
              placeholder="e.g. Missing key architectural documentation from vendor, pending security audit..."
              value={blockReason}
              onChange={(e) => setBlockReason(e.target.value)}
            />
            <div className={styles.modalActions}>
              <button className={styles.cancelBtn} onClick={() => setShowBlockModal(false)}>
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

      {/* Approve Version Modal */}
      {showApproveModal && (
        <div className={styles.modalOverlay} onClick={() => setShowApproveModal(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0 }}>Approve Handover Version Snapshot</h3>
            <p className={styles.modalSubtitle}>
              Approving creates an immutable audit snapshot of all Transfer Packs, verified claims, and evidence bindings.
              Case status will transition to <strong>APPROVED</strong>.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                Amendment / Approval Reason (Optional)
              </label>
              <textarea
                rows={3}
                placeholder="e.g. Lead verification complete; architecture and runbooks approved."
                value={amendmentReason}
                onChange={(e) => setAmendmentReason(e.target.value)}
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

            <div className={styles.modalActions}>
              <button className={styles.cancelBtn} onClick={() => setShowApproveModal(false)}>
                Cancel
              </button>
              <button
                className={`${styles.btnActionSm} ${styles.btnActionPrimary}`}
                style={{ padding: '8px 16px', fontSize: '13px' }}
                disabled={createVersionMutation.isPending}
                onClick={() =>
                  createVersionMutation.mutate({
                    amendment_reason: amendmentReason.trim() || undefined,
                  })
                }
              >
                <ShieldCheck size={14} />
                {createVersionMutation.isPending ? 'Freezing Snapshot…' : 'Freeze Approved Version'}
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
              Approved {new Date(inspectSnapshot.approved_at).toLocaleString()} by {inspectSnapshot.approved_by_name}
            </p>
            <pre className={styles.jsonViewer}>
              {JSON.stringify(inspectSnapshot.snapshot_json, null, 2)}
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
    </div>
  );
}
