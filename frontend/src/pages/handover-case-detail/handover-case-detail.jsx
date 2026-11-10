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
} from 'lucide-react';
import { caseApi } from '../../api/case.api';
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

  const { data: caseData, isLoading } = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => caseApi.getCase(caseId),
    enabled: !!caseId,
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
          <div className={styles.placeholderTab}>
            <GitBranch size={32} />
            <h3>Transfer Packs</h3>
            <p>Workstream groupings and evidence claims will appear here once AI extraction runs (Phase 6–7).</p>
          </div>
        )}

        {activeTab === 'questions' && (
          <div className={styles.placeholderTab}>
            <HelpCircle size={32} />
            <h3>Knowledge Gap Questions</h3>
            <p>Questions directed to departing team members will appear here (Phase 7).</p>
          </div>
        )}

        {activeTab === 'review' && (
          <div className={styles.placeholderTab}>
            <CheckSquare size={32} />
            <h3>Review & Approvals</h3>
            <p>Review checklists and immutable version snapshots will appear here (Phase 8).</p>
          </div>
        )}

        {activeTab === 'versions' && (
          <div className={styles.placeholderTab}>
            <History size={32} />
            <h3>Version History</h3>
            <p>Immutable snapshot history and changelogs will appear here (Phase 8).</p>
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
    </div>
  );
}
