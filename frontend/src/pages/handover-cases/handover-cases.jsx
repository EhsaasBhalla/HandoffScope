import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { FileStack, Plus, AlertTriangle, ArrowRight } from 'lucide-react';
import { projectApi } from '../../api/project.api';
import { caseApi } from '../../api/case.api';
import styles from './handover-cases.module.css';

export default function HandoverCasesPage() {
  const [statusFilter, setStatusFilter] = useState('ALL');

  // Fetch workspaces & projects
  const { data: workspaces } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => projectApi.listWorkspaces(),
  });

  const activeWsId = workspaces?.[0]?.id;

  const { data: projects } = useQuery({
    queryKey: ['projects', activeWsId],
    queryFn: () => projectApi.listProjects(activeWsId),
    enabled: !!activeWsId,
  });

  const [selectedProjectId, setSelectedProjectId] = useState('ALL');
  const defaultProjectId = projects?.[0]?.id;

  // Fetch cases across ALL projects in the workspace
  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases', 'workspace', activeWsId, projects?.map((p) => p.id)],
    queryFn: async () => {
      const results = await Promise.all(
        (projects || []).map(async (p) => {
          const list = await caseApi.listCases(p.id);
          return (list || []).map((c) => ({ ...c, project_name: p.name }));
        })
      );
      return results.flat();
    },
    enabled: !!projects && projects.length > 0,
  });

  const filteredCases = useMemo(() => {
    if (!Array.isArray(cases)) return [];
    return cases.filter((c) => {
      if (selectedProjectId !== 'ALL' && c.project_id !== selectedProjectId) return false;
      if (statusFilter === 'ALL') return true;
      if (statusFilter === 'BLOCKED') return c.is_blocked;
      return c.status === statusFilter;
    });
  }, [cases, selectedProjectId, statusFilter]);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h2>Handover Cases</h2>
          <p className={styles.subtitle}>
            Active project knowledge transitions, evidence packs, and verification pipelines.
          </p>
        </div>

        {defaultProjectId && (
          <Link
            to={`/projects/${defaultProjectId}/cases/new`}
            className={styles.createBtn}
          >
            <Plus size={16} /> New Handover Case
          </Link>
        )}
      </div>

      {/* Filter Chips */}
      <div className={styles.filterRow}>
        {['ALL', 'DRAFT', 'RECONSTRUCTING', 'UNDER_REVIEW', 'APPROVED', 'SHARED', 'BLOCKED'].map((st) => (
          <button
            key={st}
            className={`${styles.filterChip} ${statusFilter === st ? styles.activeChip : ''}`}
            onClick={() => setStatusFilter(st)}
          >
            {st.replace(/_/g, ' ')}
          </button>
        ))}
      </div>

      {/* Cases List */}
      {isLoading ? (
        <div className={styles.loading}>Loading handover cases…</div>
      ) : filteredCases && filteredCases.length > 0 ? (
        <div className={styles.list}>
          {filteredCases.map((c) => (
            <Link key={c.id} to={`/cases/${c.id}`} className={styles.caseCard}>
              <div className={styles.caseLeft}>
                <span className={styles.caseBadge}>#{c.case_number}</span>
                <div>
                  <h3 className={styles.caseTitle}>{c.title}</h3>
                  <div className={styles.metaRow}>
                    <span className={styles.metaItem}>
                      {c.transition_type.replace(/_/g, ' ')}
                    </span>
                    <span className={styles.dot}>•</span>
                    <span className={styles.metaDate}>
                      Created {new Date(c.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              </div>

              <div className={styles.caseRight}>
                {c.is_blocked && (
                  <span className={styles.blockedBadge}>
                    <AlertTriangle size={13} /> Blocked
                  </span>
                )}
                <span className={styles.statusPill}>{c.status}</span>
                <ArrowRight size={18} className={styles.arrowIcon} />
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className={styles.empty}>
          <FileStack size={40} className={styles.emptyIcon} />
          <h3>No handover cases found</h3>
          <p>Create a handover case to start importing sources and reconstructing project context.</p>
          {defaultProjectId && (
            <Link to={`/projects/${defaultProjectId}/cases/new`} className={styles.createBtn}>
              <Plus size={16} /> Create Case
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
