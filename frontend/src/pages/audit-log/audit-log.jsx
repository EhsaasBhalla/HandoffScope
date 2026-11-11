import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ShieldCheck,
  Search,
  RefreshCw,
  Filter,
  FileText,
  User,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { auditApi } from '../../api/audit.api';
import styles from './audit-log.module.css';

export default function AuditLogPage() {
  const [searchTerm, setSearchTerm] = useState('');
  const [entityFilter, setEntityFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [expandedRow, setExpandedRow] = useState(null);

  const {
    data: events,
    isLoading,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['audit-events', entityFilter, actionFilter, searchTerm],
    queryFn: () =>
      auditApi.getEvents({
        entity_type: entityFilter || undefined,
        action: actionFilter || undefined,
        search: searchTerm || undefined,
        limit: 100,
      }),
  });

  function getBadgeClass(action = '') {
    if (action.includes('created') || action.includes('connected')) return styles.badgeCreate;
    if (action.includes('accepted')) return styles.badgeAccept;
    if (action.includes('reviewed') || action.includes('reconstruction')) return styles.badgeReview;
    if (action.includes('declined') || action.includes('stale') || action.includes('revoked'))
      return styles.badgeDecline;
    if (action.includes('shared') || action.includes('acknowledged')) return styles.badgeShare;
    return styles.badgeDefault;
  }

  function formatTime(isoStr) {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      return d.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoStr;
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h2>Audit Log & Provenance</h2>
          <p className={styles.subtitle}>
            Comprehensive, immutable audit trail tracking all handover decisions, state transitions,
            claim reviews, version releases, and responsibility handovers.
          </p>
        </div>
        <button
          className={styles.refreshBtn}
          onClick={() => refetch()}
          disabled={isFetching}
          title="Refresh audit feed"
        >
          <RefreshCw size={14} className={isFetching ? styles.spin : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Filter toolbar */}
      <div className={styles.filterCard}>
        <div className={styles.searchBox}>
          <Search size={16} color="var(--color-text-muted)" />
          <input
            type="text"
            className={styles.searchInput}
            placeholder="Search by action, summary, or entity..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div className={styles.selectGroup}>
          <Filter size={14} color="var(--color-text-muted)" />
          <select
            className={styles.filterSelect}
            value={entityFilter}
            onChange={(e) => setEntityFilter(e.target.value)}
          >
            <option value="">All Entity Types</option>
            <option value="handover_case">Handover Case</option>
            <option value="transfer_pack">Transfer Pack</option>
            <option value="claim">Claim</option>
            <option value="handover_version">Version Snapshot</option>
            <option value="question">Question</option>
            <option value="responsibility_assignment">Responsibility</option>
            <option value="connected_source">Source</option>
            <option value="identity_mapping">Identity Mapping</option>
          </select>

          <select
            className={styles.filterSelect}
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
          >
            <option value="">All Actions</option>
            <option value="case.created">Case Created</option>
            <option value="RECONSTRUCTION_COMPLETED">Reconstruction Completed</option>
            <option value="claim.">Claim Reviewed / Updated</option>
            <option value="case.approved">Version Approved</option>
            <option value="case.shared">Version Shared</option>
            <option value="case.acknowledged">Case Acknowledged</option>
            <option value="responsibility.accepted">Responsibility Accepted</option>
            <option value="responsibility.declined">Responsibility Declined</option>
            <option value="question.">Question Actions</option>
            <option value="source.refreshed">Source Refreshed</option>
          </select>
        </div>
      </div>

      {/* Audit table */}
      <div className={styles.tableContainer}>
        {isLoading ? (
          <div className={styles.emptyState}>Loading audit records...</div>
        ) : !events || events.length === 0 ? (
          <div className={styles.emptyState}>
            <ShieldCheck size={36} className={styles.emptyIcon} />
            <p>No audit events match your filter criteria.</p>
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th style={{ width: '180px' }}>Timestamp</th>
                <th style={{ width: '200px' }}>Actor</th>
                <th style={{ width: '180px' }}>Action</th>
                <th style={{ width: '160px' }}>Entity</th>
                <th>Summary / Details</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td style={{ whiteSpace: 'nowrap', color: 'var(--color-text-secondary)' }}>
                    {formatTime(event.created_at)}
                  </td>
                  <td>
                    <div className={styles.actorCell}>
                      <span className={styles.actorName}>
                        {event.actor_name || 'System / Automated'}
                      </span>
                      {event.actor_email && (
                        <span className={styles.actorEmail}>{event.actor_email}</span>
                      )}
                    </div>
                  </td>
                  <td>
                    <span className={`${styles.actionBadge} ${getBadgeClass(event.action)}`}>
                      {event.action}
                    </span>
                  </td>
                  <td>
                    <div className={styles.entityInfo}>
                      <strong>{event.entity_type}</strong>
                      {event.entity_id && (
                        <div style={{ fontFamily: 'monospace', fontSize: '11px' }}>
                          {event.entity_id.slice(0, 8)}…
                        </div>
                      )}
                    </div>
                  </td>
                  <td>
                    <div>{event.summary || '—'}</div>
                    {event.details && (
                      <div>
                        <button
                          type="button"
                          className={styles.detailsBtn}
                          onClick={() =>
                            setExpandedRow(expandedRow === event.id ? null : event.id)
                          }
                        >
                          {expandedRow === event.id ? 'Hide Details' : 'View Raw Details'}
                        </button>
                        {expandedRow === event.id && (
                          <pre className={styles.detailsBox}>
                            {JSON.stringify(event.details, null, 2)}
                          </pre>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
