import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  FolderKanban,
  FileStack,
  GitBranch,
  Clock,
  HelpCircle,
  CheckCircle,
  AlertTriangle,
  PlusCircle,
  Compass,
  Sparkles,
} from 'lucide-react';
import { dashboardApi } from '../../api/dashboard.api';
import { projectApi } from '../../api/project.api';
import { useAuth } from '../../context/AuthContext';
import { JudgeGuideModal } from '../../components/judge-guide-modal/judge-guide-modal';
import styles from './overview.module.css';

export default function OverviewPage() {
  const { user } = useAuth();
  const [showGuide, setShowGuide] = useState(false);

  const { data: workspaces } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => projectApi.listWorkspaces(),
  });

  const workspaceId = workspaces?.[0]?.id;

  const { data: stats, isLoading } = useQuery({
    queryKey: ['dashboard-stats', workspaceId],
    queryFn: () => dashboardApi.getStats(workspaceId),
    enabled: !!workspaceId,
  });

  function getStatusStyle(status = '') {
    switch (status) {
      case 'TRANSFERRED':
      case 'APPROVED':
        return { background: '#dcfce7', color: '#15803d' };
      case 'UNDER_REVIEW':
      case 'NEEDS_INPUT':
      case 'PARTIALLY_ACKNOWLEDGED':
        return { background: '#fef3c7', color: '#b45309' };
      case 'SHARED':
      case 'ACKNOWLEDGED':
        return { background: '#e0f2fe', color: '#0369a1' };
      default:
        return { background: '#f1f5f9', color: '#475569' };
    }
  }

  function formatTime(isoStr) {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    } catch {
      return isoStr;
    }
  }

  return (
    <div className={styles.page}>
      {/* Top Greeting & Quick Actions */}
      <div className={styles.greeting}>
        <div>
          <h2>Welcome back, {user?.display_name?.split(' ')[0] || 'Engineer'}</h2>
          <p>Real-time knowledge reconstruction and handover transfer status.</p>
        </div>
        <div className={styles.quickActions}>
          <button className={styles.evaluatorBannerBtn} onClick={() => setShowGuide(true)}>
            <Compass size={16} />
            <span>Guide</span>
          </button>
          <Link to="/review" className={styles.actionBtn}>
            <Clock size={16} />
            <span>Review Queue</span>
          </Link>
          <Link to="/successor" className={styles.actionBtn}>
            <CheckCircle size={16} />
            <span>Successor View</span>
          </Link>
          <Link to="/cases" className={`${styles.actionBtn} ${styles.actionBtnPrimary}`}>
            <PlusCircle size={16} />
            <span>Handover Cases</span>
          </Link>
        </div>
      </div>

      {/* Guide Callout Banner */}
      <div className={styles.evaluatorBanner}>
        <div className={styles.evaluatorBannerLeft}>
          <div className={styles.evaluatorBannerIcon}>
            <Sparkles size={18} />
          </div>
          <div>
            <div className={styles.evaluatorBannerTitle}>
              Interactive Workspace Guide Available
            </div>
            <div className={styles.evaluatorBannerText}>
              Follow our self-guided 5-step walkthrough, switch between 4 demo personas in 1-click, and explore evidence-grounded handover workflows.
            </div>
          </div>
        </div>
        <button
          className={styles.evaluatorBannerOpenBtn}
          onClick={() => setShowGuide(true)}
        >
          <Compass size={16} />
          <span>Open Guide</span>
        </button>
      </div>

      {/* Real Metric Stats Grid */}
      <div className={styles.statsGrid}>
        <div className={styles.statCard}>
          <FolderKanban size={24} className={styles.statIcon} />
          <div className={styles.statContent}>
            <span className={styles.statValue}>
              {isLoading ? '…' : stats?.projects_count ?? 0}
            </span>
            <span className={styles.statLabel}>Active Projects</span>
          </div>
        </div>

        <div className={styles.statCard}>
          <FileStack size={24} className={styles.statIcon} />
          <div className={styles.statContent}>
            <span className={styles.statValue}>
              {isLoading ? '…' : stats?.active_cases_count ?? 0}
            </span>
            <span className={styles.statLabel}>Handover Cases</span>
          </div>
        </div>

        <div className={styles.statCard}>
          <GitBranch size={24} className={styles.statIcon} />
          <div className={styles.statContent}>
            <span className={styles.statValue}>
              {isLoading ? '…' : stats?.connected_sources_count ?? 0}
            </span>
            <span className={styles.statLabel}>Connected Sources</span>
          </div>
        </div>

        <div className={styles.statCard}>
          <Clock size={24} className={styles.statIcon} />
          <div className={styles.statContent}>
            <span className={styles.statValue}>
              {isLoading ? '…' : stats?.pending_reviews_count ?? 0}
            </span>
            <span className={styles.statLabel}>Pending Reviews</span>
          </div>
        </div>

        <div className={styles.statCard}>
          <HelpCircle size={24} className={styles.statIcon} />
          <div className={styles.statContent}>
            <span className={styles.statValue}>
              {isLoading ? '…' : stats?.open_questions_count ?? 0}
            </span>
            <span className={styles.statLabel}>Open Questions</span>
          </div>
        </div>
      </div>

      {/* Two-Column Dashboard Main Section */}
      <div className={styles.mainGrid}>
        {/* Left Column: Active Cases Table */}
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <h3>Active Handover Cases</h3>
            <Link to="/cases" className={styles.viewAllLink}>
              View All Cases →
            </Link>
          </div>

          <div className={styles.card}>
            {isLoading ? (
              <div style={{ padding: 'var(--space-xl)', textAlign: 'center' }}>Loading cases...</div>
            ) : !Array.isArray(stats?.active_cases) || stats.active_cases.length === 0 ? (
              <div style={{ padding: 'var(--space-2xl)', textAlign: 'center', color: 'var(--color-text-secondary)' }}>
                No active handover cases in this workspace.
              </div>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Case Title</th>
                    <th>Project</th>
                    <th>Status</th>
                    <th>Scope End</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.active_cases.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <Link to={`/cases/${c.id}`} className={styles.caseLink}>
                          {c.title}
                        </Link>
                      </td>
                      <td>
                        <span className={styles.projectName}>{c.project_name}</span>
                      </td>
                      <td>
                        <span className={styles.statusBadge} style={getStatusStyle(c.status)}>
                          {c.status}
                        </span>
                        {c.sync_status === 'CHANGED_SINCE_APPROVAL' && (
                          <span className={`${styles.syncBadge} ${styles.syncStale}`}>
                            CHANGED
                          </span>
                        )}
                        {c.sync_status === 'POTENTIALLY_STALE' && (
                          <span className={`${styles.syncBadge} ${styles.syncStale}`}>
                            STALE
                          </span>
                        )}
                        {c.sync_status === 'CURRENT' && (
                          <span className={`${styles.syncBadge} ${styles.syncCurrent}`}>
                            SYNCED
                          </span>
                        )}
                      </td>
                      <td style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
                        {formatTime(c.scope_end) || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Right Column: Needs Attention & Recent Activity */}
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <h3>Action Items</h3>
          </div>

          {/* Needs Attention Cards */}
          <div>
            {!Array.isArray(stats?.needs_attention) || stats.needs_attention.length === 0 ? (
              <div className={styles.attentionCard} style={{ borderLeft: '4px solid #10b981' }}>
                <CheckCircle size={18} color="#10b981" />
                <div>
                  <div className={styles.attentionTitle}>All caught up!</div>
                  <div className={styles.attentionSub}>No items currently require urgent attention.</div>
                </div>
              </div>
            ) : (
              stats.needs_attention.map((item, idx) => (
                <Link
                  key={idx}
                  to={item?.link || '#'}
                  className={`${styles.attentionCard} ${
                    item?.severity === 'high' ? styles.attentionHigh : styles.attentionMedium
                  }`}
                >
                  <AlertTriangle
                    size={18}
                    color={item?.severity === 'high' ? 'var(--color-error)' : 'var(--color-warning)'}
                  />
                  <div style={{ flex: 1 }}>
                    <div className={styles.attentionTitle}>{item?.title}</div>
                    <div className={styles.attentionSub}>Click to resolve in workspace →</div>
                  </div>
                </Link>
              ))
            )}
          </div>

          {/* Recent Activity */}
          <div className={styles.sectionHeader} style={{ marginTop: 'var(--space-md)' }}>
            <h3>Recent Activity</h3>
            <Link to="/audit" className={styles.viewAllLink}>
              Audit Log →
            </Link>
          </div>

          <div className={styles.card}>
            <div className={styles.activityList}>
              {!Array.isArray(stats?.recent_activity) || stats.recent_activity.length === 0 ? (
                <div style={{ padding: 'var(--space-md)', textAlign: 'center', color: 'var(--color-text-muted)' }}>
                  No recent activity recorded.
                </div>
              ) : (
                stats.recent_activity.map((act) => (
                  <div key={act.id} className={styles.activityItem}>
                    <div className={styles.activityDot} />
                    <div className={styles.activityContent}>
                      <span className={styles.activitySummary}>{act.summary}</span>
                      <span className={styles.activityMeta}>
                        {act.actor_name} • {formatTime(act.created_at)}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      <JudgeGuideModal
        isOpen={showGuide}
        onClose={() => setShowGuide(false)}
      />
    </div>
  );
}
