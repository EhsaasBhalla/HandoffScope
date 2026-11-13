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
  Download,
  FileArchive,
  MessageSquare,
  UserPlus,
  RotateCcw,
  Radio,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { usePermissions } from '../../hooks/usePermissions';
import { useCaseLiveUpdates } from '../../hooks/useCaseLiveUpdates';
import { recipientApi } from '../../api/recipient.api';
import { exportApi } from '../../api/export.api';
import { HandoverChatDrawer } from '../../components/handover-chat-drawer/handover-chat-drawer';
import styles from './successor-view.module.css';

export default function SuccessorViewPage() {
  const { user } = useAuth();
  const { hasCapability } = usePermissions();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const urlCaseId = searchParams.get('caseId');
  const [selectedCaseId, setSelectedCaseId] = useState(urlCaseId || '');
  const [completedActions, setCompletedActions] = useState({});
  const [expandedPacks, setExpandedPacks] = useState({});

  // Decline Modal, Claim Delegation Modal & Export state
  const [decliningAssignmentId, setDecliningAssignmentId] = useState(null);
  const [declineReason, setDeclineReason] = useState('');
  const [declineError, setDeclineError] = useState('');
  const [delegatingClaim, setDelegatingClaim] = useState(null);
  const [delegateUserId, setDelegateUserId] = useState('');
  const [delegateNote, setDelegateNote] = useState('');
  const [delegateError, setDelegateError] = useState('');
  const [exportBusy, setExportBusy] = useState('');
  const [exportError, setExportError] = useState('');
  const [chatOpen, setChatOpen] = useState(false);

  const closeDeclineModal = () => {
    setDecliningAssignmentId(null);
    setDeclineReason('');
    setDeclineError('');
  };

  const closeDelegateModal = () => {
    setDelegatingClaim(null);
    setDelegateUserId('');
    setDelegateNote('');
    setDelegateError('');
  };

  const { mode: liveMode } = useCaseLiveUpdates(selectedCaseId);

  // 1. Fetch cases shared with this user as successor
  const { data: myCases, isLoading: casesLoading } = useQuery({
    queryKey: ['my-successor-cases'],
    queryFn: () => recipientApi.listMySuccessorCases(),
  });

  useEffect(() => {
    if (urlCaseId && urlCaseId !== selectedCaseId) {
      setSelectedCaseId(urlCaseId);
    }
  }, [urlCaseId]);

  useEffect(() => {
    if (myCases && myCases.length > 0) {
      const stillValid = myCases.some((c) => c.id === selectedCaseId);
      if (!selectedCaseId || !stillValid) {
        const nextId = (urlCaseId && myCases.some((c) => c.id === urlCaseId)) ? urlCaseId : myCases[0].id;
        setSelectedCaseId(nextId);
        setSearchParams({ caseId: nextId });
      }
    } else if (myCases && myCases.length === 0) {
      setSelectedCaseId('');
    }
  }, [myCases, selectedCaseId, urlCaseId, setSearchParams]);

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
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['case-shares', selectedCaseId] });
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
      queryClient.invalidateQueries({ queryKey: ['cases'] });
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
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['case-responsibilities', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      closeDeclineModal();
    },
    onError: (err) => {
      setDeclineError(err.data?.detail || err.message || 'Failed to decline responsibility (reason must be at least 3 characters)');
    },
  });

  // Delegate Claim Mutation
  const delegateMutation = useMutation({
    mutationFn: ({ claimId, assignedUserId, note }) =>
      recipientApi.delegateClaim(claimId, {
        assigned_user_id: assignedUserId,
        note: note || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
      queryClient.invalidateQueries({ queryKey: ['case', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['case-responsibilities', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      closeDelegateModal();
    },
    onError: (err) => {
      setDelegateError(err.data?.detail || err.message || 'Failed to delegate claim.');
    },
  });

  // Revoke Claim Delegation Mutation
  const revokeDelegationMutation = useMutation({
    mutationFn: (assignmentId) => recipientApi.revokeDelegation(assignmentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['successor-continuation-view', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['my-successor-cases'] });
      queryClient.invalidateQueries({ queryKey: ['case', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['case-responsibilities', selectedCaseId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
    onError: (err) => {
      alert(err.data?.detail || err.message || 'Failed to revoke claim delegation');
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
                    backgroundColor: 'var(--color-warning-bg)',
                    color: 'var(--color-warning)',
                    border: '1px solid var(--color-warning)',
                  }}
                >
                  Draft Preview — Not Approved
                </span>
              ) : (
                <>
                  <span
                    style={{
                      fontSize: '11px',
                      fontWeight: 600,
                      padding: '3px 8px',
                      borderRadius: '999px',
                      backgroundColor: 'var(--color-success-bg)',
                      color: 'var(--color-success)',
                      border: '1px solid var(--color-success)',
                    }}
                  >
                    {v.is_snapshot_backed ? 'Immutable Frozen Snapshot' : 'Approved Snapshot'} v{v.current_version_number || 1}
                    {v.approved_at ? ` • Approved ${new Date(v.approved_at).toLocaleString()}` : ''}
                  </span>
                  {v.current_version_number >= 1 && (
                    <>
                      <button
                        type="button"
                        disabled={exportBusy === 'pdf'}
                        onClick={async () => {
                          setExportError('');
                          setExportBusy('pdf');
                          try {
                            await exportApi.downloadCertificatePdf(selectedCaseId, v.current_version_number);
                          } catch (err) {
                            setExportError(err.message || 'PDF download failed.');
                          } finally {
                            setExportBusy('');
                          }
                        }}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '5px',
                          fontSize: '11px',
                          fontWeight: 600,
                          padding: '3px 9px',
                          borderRadius: '6px',
                          border: '1px solid var(--color-border)',
                          backgroundColor: 'var(--color-bg-secondary)',
                          color: 'var(--color-text-primary)',
                        }}
                      >
                        <Download size={12} />
                        {exportBusy === 'pdf' ? 'Generating PDF…' : 'Certificate PDF'}
                      </button>
                      <button
                        type="button"
                        disabled={exportBusy === 'zip'}
                        onClick={async () => {
                          setExportError('');
                          setExportBusy('zip');
                          try {
                            await exportApi.downloadComplianceBundle(selectedCaseId, v.current_version_number);
                          } catch (err) {
                            setExportError(err.message || 'Archive download failed.');
                          } finally {
                            setExportBusy('');
                          }
                        }}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '5px',
                          fontSize: '11px',
                          fontWeight: 600,
                          padding: '3px 9px',
                          borderRadius: '6px',
                          border: 'none',
                          backgroundColor: 'var(--color-accent)',
                          color: 'var(--color-text-inverse)',
                        }}
                      >
                        <FileArchive size={12} />
                        {exportBusy === 'zip' ? 'Packaging ZIP…' : 'Compliance Archive (.zip)'}
                      </button>
                    </>
                  )}
                  <span
                    title={liveMode === 'live' ? 'Real-time SSE stream connected' : 'Periodic sync fallback active'}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                      fontSize: '11px',
                      padding: '3px 8px',
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
                    onClick={() => setChatOpen(true)}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                      fontSize: '11px',
                      fontWeight: 600,
                      padding: '3px 9px',
                      borderRadius: '6px',
                      border: '1px solid var(--color-border-accent)',
                      backgroundColor: 'var(--color-accent-subtle)',
                      color: 'var(--color-accent-text)',
                    }}
                  >
                    <MessageSquare size={12} /> Ask Handover Assistant
                  </button>
                </>
              )}
            </div>
          )}
          {exportError && (
            <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--color-error)' }}>
              {exportError}
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
                    ? `Acknowledged on ${v.acknowledged_at ? new Date(v.acknowledged_at).toLocaleString() : 'N/A'} for Version ${v.current_version_number || 1}. Case status: ${v.status}.`
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
                {v.stats?.assigned_packs ?? 0} / {v.stats?.total_packs ?? 0}
              </span>
            </div>

            <div className={styles.statCard}>
              <div className={styles.statHeader}>
                <span>Accepted Ownership</span>
                <CheckCircle2 size={16} style={{ color: 'var(--color-success)' }} />
              </div>
              <span className={styles.statValue} style={{ color: 'var(--color-success)' }}>
                {v.stats?.accepted_packs ?? 0}
              </span>
            </div>

            <div className={styles.statCard}>
              <div className={styles.statHeader}>
                <span>Next Actions</span>
                <CheckSquare size={16} style={{ color: 'var(--color-accent)' }} />
              </div>
              <span className={styles.statValue}>
                {v.stats?.next_actions_count ?? 0}
              </span>
            </div>

            <div className={styles.statCard}>
              <div className={styles.statHeader}>
                <span>Access Blockers</span>
                <ShieldAlert size={16} style={{ color: (v.stats?.access_blockers_count ?? 0) > 0 ? 'var(--color-error)' : 'var(--color-text-muted)' }} />
              </div>
              <span
                className={styles.statValue}
                style={{ color: (v.stats?.access_blockers_count ?? 0) > 0 ? 'var(--color-error)' : 'var(--color-text-primary)' }}
              >
                {v.stats?.access_blockers_count ?? 0}
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
              {(v.transfer_packs || []).map((pack) => {
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
                          ) : assignment.assigned_user_id === user?.id ? (
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
                                onClick={() => {
                                  setDecliningAssignmentId(assignment.id);
                                  setDeclineReason('');
                                  setDeclineError('');
                                }}
                              >
                                <XCircle size={14} /> Decline
                              </button>
                            </>
                          ) : (
                            <span className={styles.statusPillPending}>
                              Pending Acceptance ({assignment.assignee_name || 'Successor'})
                            </span>
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
                        {isExpanded ? 'Hide Claims' : `View ${(pack.claims || []).length} Claims`}
                      </button>

                      {isExpanded && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-xs)', marginTop: 'var(--space-sm)' }}>
                          {(pack.claims || []).map((c) => {
                            const activeDelegation = (v.claim_assignments || []).find((ca) => ca.claim_id === c.id);
                            const eligibleTargets = (v.eligible_delegates || []).filter((m) => m.user_id !== user?.id);
                            const canDelegateClaim =
                              Boolean(assignment && assignment.assigned_user_id === user?.id) &&
                              !activeDelegation &&
                              eligibleTargets.length > 0;
                            return (
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
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: '2px' }}>
                                  <div style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                                    [{c.claim_type}] {c.title}
                                  </div>
                                  {activeDelegation ? (
                                    <span style={{ fontSize: '11px', color: 'var(--color-accent-text)', fontWeight: 600 }}>
                                      Delegated → {activeDelegation.assignee_name} ({(activeDelegation.status || '').replace(/_/g, ' ')})
                                    </span>
                                  ) : canDelegateClaim ? (
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setDelegatingClaim({ claim: c, packName: pack.name });
                                        setDelegateUserId(eligibleTargets[0]?.user_id || '');
                                        setDelegateNote('');
                                        setDelegateError('');
                                      }}
                                      style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '4px',
                                        fontSize: '11px',
                                        padding: '2px 8px',
                                        borderRadius: 'var(--radius-sm)',
                                        border: '1px solid var(--color-border)',
                                        backgroundColor: 'var(--color-bg-secondary)',
                                        color: 'var(--color-text-primary)',
                                        cursor: 'pointer',
                                      }}
                                    >
                                      <UserPlus size={11} /> Delegate
                                    </button>
                                  ) : null}
                                </div>
                                <div style={{ color: c.is_restricted_withheld ? 'var(--color-error)' : 'var(--color-text-secondary)' }}>
                                  {c.body_text}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {(v.claim_assignments || []).length > 0 && (
            <div className={styles.section}>
              <div className={styles.sectionHeader}>
                <h3 className={styles.sectionTitle}>
                  <UserPlus size={20} style={{ color: 'var(--color-accent)' }} />
                  Delegated Claim Responsibilities ({(v.claim_assignments || []).length})
                </h3>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                {(v.claim_assignments || []).map((ca) => {
                  const isAssignee = ca.assigned_user_id === user?.id;
                  const canRevoke = ca.delegated_from_user_id === user?.id || ca.assigned_by === user?.id;
                  return (
                    <div key={ca.id} className={styles.packCard}>
                      <div className={styles.packTop}>
                        <div className={styles.packInfo}>
                          <h4>{ca.claim_title || 'Delegated Claim'}</h4>
                          <div className={styles.packMeta}>
                            <span>Pack: {ca.transfer_pack_name}</span>
                            <span>•</span>
                            <span>From {ca.delegated_from_name || 'Owner'} → {ca.assignee_name}</span>
                          </div>
                          {ca.delegation_note && (
                            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
                              Note: {ca.delegation_note}
                            </div>
                          )}
                        </div>
                        <div className={styles.actionsRow}>
                          {ca.status === 'ACCEPTED' ? (
                            <span className={styles.statusPillAccepted}>Accepted</span>
                          ) : ca.status === 'DECLINED' ? (
                            <span className={styles.statusPillDeclined}>Declined</span>
                          ) : isAssignee ? (
                            <>
                              <button
                                className={styles.btnAccept}
                                onClick={() => acceptMutation.mutate(ca.id)}
                                disabled={acceptMutation.isPending}
                              >
                                <CheckCircle2 size={14} /> Accept
                              </button>
                              <button
                                className={styles.btnDecline}
                                onClick={() => {
                                  setDecliningAssignmentId(ca.id);
                                  setDeclineReason('');
                                  setDeclineError('');
                                }}
                              >
                                <XCircle size={14} /> Decline
                              </button>
                            </>
                          ) : (
                            <span className={styles.statusPillPending}>Pending Acceptance</span>
                          )}
                          {canRevoke && (
                            <button
                              type="button"
                              className={styles.btnDecline}
                              onClick={() => revokeDelegationMutation.mutate(ca.id)}
                              disabled={revokeDelegationMutation.isPending}
                            >
                              <RotateCcw size={13} /> Revoke
                            </button>
                          )}
                        </div>
                      </div>
                      {ca.decline_reason && (
                        <div className={styles.declineReasonBox}>
                          <strong>Decline Reason:</strong> {ca.decline_reason}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 2. What Are My Next Actions? */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <h3 className={styles.sectionTitle}>
                <CheckSquare size={20} style={{ color: 'var(--color-accent)' }} />
                2. What Are My Next Actions? ({(v.next_actions || []).length})
              </h3>
            </div>

            {!v.next_actions || v.next_actions.length === 0 ? (
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', margin: 0 }}>
                No explicit next actions defined.
              </p>
            ) : (
              <div className={styles.actionsList}>
                {(v.next_actions || []).map((act) => {
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

            {!v.unfinished_items || v.unfinished_items.length === 0 ? (
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', margin: 0 }}>
                No unfinished inquiries or open knowledge gaps recorded.
              </p>
            ) : (
              <div className={styles.unfinishedList}>
                {(v.unfinished_items || []).map((item, idx) => (
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
                <Lock size={20} style={{ color: 'var(--color-error)' }} />
                4. What Do I Not Have Access To? (Access Blockers)
              </h3>
            </div>

            {!v.access_blockers || v.access_blockers.length === 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-success)', fontSize: 'var(--text-xs)' }}>
                <CheckCircle2 size={16} /> All referenced sources and evidence are fully accessible with your clearance.
              </div>
            ) : (
              <div className={styles.blockersList}>
                {(v.access_blockers || []).map((b, idx) => (
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
                    <span style={{ fontSize: '11px', color: 'var(--color-error)', fontWeight: 600 }}>
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
        <div className={styles.modalOverlay} onClick={closeDeclineModal}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0, fontSize: 'var(--text-lg)', color: 'var(--color-text-primary)' }}>
              Decline Responsibility for Transfer Pack
            </h3>
            <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
              Please explain why you are unable to accept ownership (e.g. missing cluster permissions, unassigned training, incorrect workstream).
            </p>

            {declineError && (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-error)', padding: '6px 8px', borderRadius: '4px', backgroundColor: 'var(--color-error-bg)' }}>
                {declineError}
              </div>
            )}

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
                onClick={closeDeclineModal}
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

      {/* Claim Delegation Modal */}
      {delegatingClaim && (
        <div className={styles.modalOverlay} onClick={closeDelegateModal}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: 0, fontSize: 'var(--text-lg)', color: 'var(--color-text-primary)' }}>
              Delegate Claim Responsibility
            </h3>
            <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
              Assign <strong>{delegatingClaim.claim.title}</strong> ({delegatingClaim.packName}) to an active project member. Restricted claims require matching member clearance.
            </p>
            <select
              value={delegateUserId}
              onChange={(e) => setDelegateUserId(e.target.value)}
              style={{
                width: '100%',
                padding: 'var(--space-sm)',
                backgroundColor: 'var(--color-bg-primary)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--color-text-primary)',
                fontSize: 'var(--text-sm)',
              }}
            >
              <option value="">Select a member...</option>
              {(v?.eligible_delegates || [])
                .filter((m) => m.user_id !== user?.id)
                .map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.display_name} ({m.role})
                  </option>
                ))}
            </select>
            <textarea
              rows={2}
              placeholder="Optional delegation context or handoff note..."
              value={delegateNote}
              onChange={(e) => setDelegateNote(e.target.value)}
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
            {delegateError && (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-error)' }}>
                {delegateError}
              </div>
            )}
            <div className={styles.modalActions}>
              <button
                type="button"
                className={styles.btnDecline}
                style={{ backgroundColor: 'transparent', color: 'var(--color-text-secondary)', borderColor: 'var(--color-border)' }}
                onClick={closeDelegateModal}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.btnAccept}
                disabled={!delegateUserId || delegateMutation.isPending}
                onClick={() =>
                  delegateMutation.mutate({
                    claimId: delegatingClaim.claim.id,
                    assignedUserId: delegateUserId,
                    note: delegateNote.trim(),
                  })
                }
              >
                {delegateMutation.isPending ? 'Delegating…' : 'Confirm Delegation'}
              </button>
            </div>
          </div>
        </div>
      )}

      {selectedCaseId && (
        <HandoverChatDrawer
          isOpen={chatOpen}
          onClose={() => setChatOpen(false)}
          caseId={selectedCaseId}
          hasApprovedVersion={Boolean(v && !v.is_draft_preview && v.current_version_number >= 1)}
          approvedVersionNumber={v?.current_version_number || null}
          isRecipientOnly={true}
        />
      )}
    </div>
  );
}
