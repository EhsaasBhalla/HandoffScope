import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, Link } from 'react-router-dom';
import {
  UserCheck,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ShieldAlert,
  ArrowRight,
  FolderKanban,
  FileCheck2,
  Layers,
  HelpCircle,
  XCircle,
  Lock,
  ChevronDown,
  ChevronUp,
  CheckSquare,
  Sparkles,
} from 'lucide-react';
import { recipientApi } from '../../api/recipient.api';
import styles from './successor-view.module.css';

export default function SuccessorViewPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const [selectedCaseId, setSelectedCaseId] = useState(searchParams.get('caseId') || '');
  const [completedActions, setCompletedActions] = useState({});
  const [expandedPacks, setExpandedPacks] = useState({});

  // Decline Modal state
  const [decliningAssignmentId, setDecliningAssignmentId] = useState(null);
  const [declineReason, setDeclineReason] = useState('');

  // 1. Fetch cases shared with this user as successor
  const { data: myCases, isLoading: casesLoading } = useQuery({
    queryKey: ['my-successor-cases'],
    queryFn: () => recipientApi.listMySuccessorCases(),
  });

  useEffect(() => {
    if (myCases && myCases.length > 0) {
      const stillValid = myCases.some((c) => c.id === selectedCaseId);
      if (!selectedCaseId || !stillValid) {
        setSelectedCaseId(myCases[0].id);
        setSearchParams({ caseId: myCases[0].id });
      }
    } else {
      setSelectedCaseId('');
    }
  }, [myCases, selectedCaseId]);

  const handleCaseChange = (e) => {
    const newId = e.target.value;
    setSelectedCaseId(newId);
    setSearchParams({ caseId: newId });
  };

  // 2. Fetch full Continuation View for active case
  const { data: continuationView, isLoading: viewLoading } = useQuery({
    queryKey: ['successor-continuation-view', selectedCaseId],
    queryFn: () => recipientApi.getSuccessorView(selectedCaseId),
    enabled: !!selectedCaseId,
  });

  // Acknowledge Receipt Mutation
  const ackMutation = useMutation({
    mutationFn: () => recipientApi.acknowledgeCase(selectedCaseId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
      queryClient.invalidateQueries({ queryKey: ['case', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to acknowledge receipt');
    },
  });

  // Accept Responsibility Mutation
  const acceptMutation = useMutation({
    mutationFn: (assignmentId) => recipientApi.acceptResponsibility(assignmentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
      queryClient.invalidateQueries({ queryKey: ['case', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-responsibilities', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to accept responsibility');
    },
  });

  // Decline Responsibility Mutation
  const declineMutation = useMutation({
    mutationFn: ({ assignmentId, reason }) =>
      recipientApi.declineResponsibility(assignmentId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
      queryClient.invalidateQueries({ queryKey: ['case', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['case-responsibilities', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      setDecliningAssignmentId(null);
      setDeclineReason('');
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to decline responsibility (reason must be at least 3 characters)');
    },
  });

  const toggleActionDone = (id) => {
    setCompletedActions((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const togglePackExpand = (id) => {
    setExpandedPacks((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  if (casesLoading) {
    return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--color-text-muted)' }}>Loading successor transfers…</div>;
  }

  if (!myCases || myCases.length === 0) {
    return (
      <div className={styles.emptyState}>
        <UserCheck size={48} style={{ color: 'var(--color-text-muted)' }} />
        <h3>No Handover Transfers Assigned</h3>
        <p>When a team lead shares an approved handover version or assigns you a Transfer Pack, it will appear here.</p>
        <Link to="/cases" style={{ marginTop: '1rem', color: 'var(--color-accent-text)' }}>
          Browse Project Handover Cases <ArrowRight size={14} style={{ display: 'inline' }} />
        </Link>
      </div>
    );
  }

  const v = continuationView;

  return (
    <div className={styles.page}>
      {/* Header with Case Selector */}
      <div className={styles.header}>
        <div className={styles.titleArea}>
          <h2>
            <UserCheck size={26} style={{ color: 'var(--color-accent)' }} />
            Successor Continuation Workspace
          </h2>
          <p className={styles.subtitle}>
            Review operational responsibilities, acknowledge receipt, inspect access blockers, and execute next actions.
          </p>
          {v && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '6px', flexWrap: 'wrap' }}>
              {v.is_draft_preview ? (
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 600,
                    padding: '3px 8px',
                    borderRadius: '999px',
                    backgroundColor: 'rgba(245, 158, 11, 0.14)',
                    color: '#fbbf24',
                    border: '1px solid rgba(245, 158, 11, 0.35)',
                  }}
                >
                  Draft Preview — Not Approved
                </span>
              ) : (
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 600,
                    padding: '3px 8px',
                    borderRadius: '999px',
                    backgroundColor: 'rgba(16, 185, 129, 0.12)',
                    color: '#34d399',
                    border: '1px solid rgba(16, 185, 129, 0.35)',
                  }}
                >
                  {v.is_snapshot_backed ? 'Immutable Frozen Snapshot' : 'Approved Snapshot'} v{v.current_version_number || 1}
                  {v.approved_at ? ` • Approved ${new Date(v.approved_at).toLocaleString()}` : ''}
                </span>
              )}
            </div>
          )}
        </div>

        <div className={styles.caseSelectorWrap}>
          <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
            Active Transition:
          </label>
          <select
            className={styles.caseSelect}
            value={selectedCaseId}
            onChange={handleCaseChange}
          >
            {myCases.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.case_number} — {c.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      {v && (
        <>
          {/* Formal Acknowledgement Banner */}
          <div
            className={`${styles.ackBanner} ${
              v.is_acknowledged ? styles.ackBannerAcknowledged : styles.ackBannerPending
            }`}
          >
            <div className={styles.ackInfo}>
              {v.is_acknowledged ? (
                <CheckCircle2 size={24} className={styles.ackIconAcknowledged} />
              ) : (
                <Clock size={24} className={styles.ackIconPending} />
              )}
              <div>
                <div className={styles.ackTitle}>
                  {v.is_acknowledged
                    ? 'Handover Receipt Acknowledged'
                    : 'Formal Handover Receipt Pending'}
                </div>
                <p className={styles.ackSub}>
                  {v.is_acknowledged
                    ? `Acknowledged on ${new Date(v.acknowledged_at).toLocaleString()} for Version ${v.current_version_number || 1}. Case status: ${v.status}.`
                    : `Departing engineer ${v.departing_contributor_name || 'Contributor'} has finalized this transition. Please acknowledge receipt to begin review.`}
                </p>
              </div>
            </div>

            {!v.is_acknowledged && (
              <button
                className={styles.ackBtn}
                onClick={() => ackMutation.mutate()}
                disabled={ackMutation.isPending}
              >
                <CheckCircle2 size={16} />
                {ackMutation.isPending ? 'Confirming…' : 'Confirm Receipt of Handover'}
              </button>
            )}
          </div>

          {/* Metric Stats Grid */}
          <div className={styles.statsGrid}>
            <div className={styles.statCard}>
              <div className={styles.statHeader}>
                <span>Assigned Packs</span>
                <Layers size={16} />
              </div>
              <span className={styles.statValue}>
                {v.stats.assigned_packs} / {v.stats.total_packs}
              </span>
            </div>

            <div className={styles.statCard}>
              <div className={styles.statHeader}>
                <span>Accepted Ownership</span>
                <CheckCircle2 size={16} style={{ color: '#34d399' }} />
              </div>
              <span className={styles.statValue} style={{ color: '#34d399' }}>
                {v.stats.accepted_packs}
              </span>
            </div>

            <div className={styles.statCard}>
              <div className={styles.statHeader}>
                <span>Next Actions</span>
                <CheckSquare size={16} style={{ color: 'var(--color-accent)' }} />
              </div>
              <span className={styles.statValue}>
                {v.stats.next_actions_count}
              </span>
            </div>

            <div className={styles.statCard}>
              <div className={styles.statHeader}>
                <span>Access Blockers</span>
                <ShieldAlert size={16} style={{ color: v.stats.access_blockers_count > 0 ? '#f87171' : 'var(--color-text-muted)' }} />
              </div>
              <span
                className={styles.statValue}
                style={{ color: v.stats.access_blockers_count > 0 ? '#f87171' : 'var(--color-text-primary)' }}
              >
                {v.stats.access_blockers_count}
              </span>
            </div>
          </div>

          {/* 1. What Am I Taking Over? (Assigned Transfer Packs) */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <h3 className={styles.sectionTitle}>
                <Layers size={20} style={{ color: 'var(--color-accent)' }} />
                1. What Am I Taking Over? (Assigned Transfer Packs)
              </h3>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
              {v.transfer_packs.map((pack) => {
                const assignment = pack.assignment;
                const isExpanded = !!expandedPacks[pack.id];

                return (
                  <div key={pack.id} className={styles.packCard}>
                    <div className={styles.packTop}>
                      <div className={styles.packInfo}>
                        <h4>{pack.name}</h4>
                        <div className={styles.packMeta}>
                          <span>{pack.component_area || 'Core Area'}</span>
                          <span>•</span>
                          <span>{pack.claims_count} Grounded Claims</span>
                          {assignment && (
                            <>
                              <span>•</span>
                              <span>Assigned to You</span>
                            </>
                          )}
                        </div>
                      </div>

                      {assignment ? (
                        <div className={styles.actionsRow}>
                          {assignment.status === 'ACCEPTED' ? (
                            <span className={styles.statusPillAccepted}>Ownership Accepted</span>
                          ) : assignment.status === 'DECLINED' ? (
                            <span className={styles.statusPillDeclined}>Ownership Declined</span>
                          ) : (
                            <>
                              <button
                                className={styles.btnAccept}
                                onClick={() => acceptMutation.mutate(assignment.id)}
                                disabled={acceptMutation.isPending}
                              >
                                <CheckCircle2 size={14} /> Accept Ownership
                              </button>
                              <button
                                className={styles.btnDecline}
                                onClick={() => setDecliningAssignmentId(assignment.id)}
                              >
                                <XCircle size={14} /> Decline
                              </button>
                            </>
                          )}
                        </div>
                      ) : (
                        <span className={styles.statusPillPending} style={{ color: 'var(--color-text-muted)', backgroundColor: 'transparent' }}>
                          Shared Reference
                        </span>
                      )}
                    </div>

                    {pack.description && (
                      <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                        {pack.description}
                      </p>
                    )}

                    {assignment?.decline_reason && (
                      <div className={styles.declineReasonBox}>
                        <strong>Decline Reason:</strong> {assignment.decline_reason}
                      </div>
                    )}

                    {/* Claims Expansion */}
                    <div style={{ borderTop: '1px solid var(--color-border-subtle)', paddingTop: 'var(--space-xs)' }}>
                      <button
                        onClick={() => togglePackExpand(pack.id)}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--color-accent-text)',
                          fontSize: 'var(--text-xs)',
                          cursor: 'pointer',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          padding: '4px 0',
                        }}
                      >
                        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        {isExpanded ? 'Hide Claims' : `View ${pack.claims.length} Claims`}
                      </button>

                      {isExpanded && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-xs)', marginTop: 'var(--space-sm)' }}>
                          {pack.claims.map((c) => (
                            <div
                              key={c.id}
                              style={{
                                padding: 'var(--space-sm)',
                                backgroundColor: 'var(--color-bg-primary)',
                                borderRadius: 'var(--radius-sm)',
                                border: '1px solid var(--color-border-subtle)',
                                fontSize: 'var(--text-xs)',
                              }}
                            >
                              <div style={{ fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: '2px' }}>
                                [{c.claim_type}] {c.title}
                              </div>
                              <div style={{ color: c.is_restricted_withheld ? '#f87171' : 'var(--color-text-secondary)' }}>
                                {c.body_text}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 2. What Are My Next Actions? */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <h3 className={styles.sectionTitle}>
                <CheckSquare size={20} style={{ color: 'var(--color-accent)' }} />
                2. What Are My Next Actions? ({v.next_actions.length})
              </h3>
            </div>

            {v.next_actions.length === 0 ? (
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', margin: 0 }}>
                No explicit next actions defined.
              </p>
            ) : (
              <div className={styles.actionsList}>
                {v.next_actions.map((act) => {
                  const isDone = !!completedActions[act.id];
                  return (
                    <div key={act.id} className={styles.actionItem}>
                      <input
                        type="checkbox"
                        checked={isDone}
                        onChange={() => toggleActionDone(act.id)}
                        className={styles.checkbox}
                      />
                      <div className={styles.actionText}>
                        <span
                          className={styles.actionTitle}
                          style={{ textDecoration: isDone ? 'line-through' : 'none', opacity: isDone ? 0.6 : 1 }}
                        >
                          {act.title}
                        </span>
                        <span className={styles.actionDesc}>
                          {act.body_text}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 3. What's Unfinished? (Knowledge Gaps & Open Questions) */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <h3 className={styles.sectionTitle}>
                <HelpCircle size={20} style={{ color: '#60a5fa' }} />
                3. What's Unfinished? (Knowledge Gaps & Inquiries)
              </h3>
            </div>

            {v.unfinished_items.length === 0 ? (
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', margin: 0 }}>
                No unfinished inquiries or open knowledge gaps recorded.
              </p>
            ) : (
              <div className={styles.unfinishedList}>
                {v.unfinished_items.map((item, idx) => (
                  <div key={idx} className={styles.unfinishedCard}>
                    <div className={styles.unfinishedTop}>
                      <span style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--color-accent)', fontWeight: 600 }}>
                        {item.type} • {item.pack_name}
                      </span>
                      <span style={{ fontSize: '10px', color: 'var(--color-text-muted)' }}>
                        {item.priority}
                      </span>
                    </div>
                    <span className={styles.unfinishedTitle}>{item.title}</span>
                    <span className={styles.unfinishedDesc}>{item.description}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 4. What Do I Not Have Access To? (Access Blockers) */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <h3 className={styles.sectionTitle}>
                <Lock size={20} style={{ color: '#f87171' }} />
                4. What Do I Not Have Access To? (Access Blockers)
              </h3>
            </div>

            {v.access_blockers.length === 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#34d399', fontSize: 'var(--text-xs)' }}>
                <CheckCircle2 size={16} /> All referenced sources and evidence are fully accessible with your clearance.
              </div>
            ) : (
              <div className={styles.blockersList}>
                {v.access_blockers.map((b, idx) => (
                  <div key={idx} className={styles.blockerItem}>
                    <div className={styles.blockerLeft}>
                      <ShieldAlert size={20} className={styles.blockerIcon} />
                      <div>
                        <div className={styles.blockerTitle}>{b.claim_title}</div>
                        <div className={styles.blockerReason}>
                          {b.reason} — Reference locator: <code>{b.locator}</code> ({b.pack_name})
                        </div>
                      </div>
                    </div>
                    <span style={{ fontSize: '11px', color: '#f87171', fontWeight: 600 }}>
                      RESTRICTED
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* Decline Responsibility Modal */}
      {decliningAssignmentId && (
        <div className={styles.modalOverlay} onClick={() => setDecliningAssignmentId(null)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0, fontSize: 'var(--text-lg)', color: 'var(--color-text-primary)' }}>
              Decline Responsibility for Transfer Pack
            </h3>
            <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
              Please explain why you are unable to accept ownership (e.g. missing cluster permissions, unassigned training, incorrect workstream).
            </p>

            <textarea
              rows={3}
              placeholder="Provide a specific rationale for declining..."
              value={declineReason}
              onChange={(e) => setDeclineReason(e.target.value)}
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

            <div className={styles.modalActions}>
              <button
                className={styles.btnDecline}
                style={{ backgroundColor: 'transparent', color: 'var(--color-text-secondary)' }}
                onClick={() => setDecliningAssignmentId(null)}
              >
                Cancel
              </button>
              <button
                className={styles.btnDecline}
                disabled={declineReason.trim().length < 3 || declineMutation.isPending}
                title={declineReason.trim().length < 3 ? 'Reason must be at least 3 characters' : ''}
                onClick={() =>
                  declineMutation.mutate({
                    assignmentId: decliningAssignmentId,
                    reason: declineReason.trim(),
                  })
                }
              >
                {declineMutation.isPending ? 'Submitting…' : 'Confirm Decline'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
