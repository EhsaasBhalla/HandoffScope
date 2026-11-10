import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  FolderKanban,
  FileStack,
  GitBranch,
  Users,
  Plus,
  ExternalLink,
  Calendar,
  AlertTriangle,
} from 'lucide-react';
import { projectApi } from '../../api/project.api';
import { caseApi } from '../../api/case.api';
import { sourceApi } from '../../api/source.api';
import styles from './project-detail.module.css';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'cases', label: 'Handover Cases' },
  { id: 'sources', label: 'Sources' },
  { id: 'people', label: 'People' },
];

export default function ProjectDetailPage() {
  const { projectId } = useParams();
  const [activeTab, setActiveTab] = useState('overview');

  // Fetch project details
  const { data: project, isLoading: projLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectApi.getProject(projectId),
    enabled: !!projectId,
  });

  // Fetch project members
  const { data: members } = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => projectApi.listProjectMembers(projectId),
    enabled: !!projectId,
  });

  // Fetch project cases
  const { data: cases } = useQuery({
    queryKey: ['cases', projectId],
    queryFn: () => caseApi.listCases(projectId),
    enabled: !!projectId,
  });

  // Fetch project sources
  const { data: sources } = useQuery({
    queryKey: ['sources', projectId],
    queryFn: () => sourceApi.listSources(projectId),
    enabled: !!projectId,
  });

  if (projLoading) {
    return <div className={styles.loading}>Loading project details…</div>;
  }

  if (!project) {
    return (
      <div className={styles.empty}>
        <h3>Project not found</h3>
        <Link to="/projects">Return to projects</Link>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Top Banner / Info */}
      <div className={styles.header}>
        <div className={styles.headerMain}>
          <div className={styles.titleRow}>
            <h2>{project.name}</h2>
            <span className={styles.slugBadge}>{project.slug}</span>
          </div>
          <p className={styles.desc}>{project.description || 'No description provided.'}</p>
          {project.repo_url && (
            <a
              href={project.repo_url}
              target="_blank"
              rel="noreferrer"
              className={styles.repoLink}
            >
              <GitBranch size={14} />
              <span>{project.repo_url}</span>
              <ExternalLink size={12} />
            </a>
          )}
        </div>

        <div className={styles.headerActions}>
          <Link
            to={`/projects/${projectId}/cases/new`}
            className={styles.primaryBtn}
          >
            <Plus size={16} /> Create Handover Case
          </Link>
        </div>
      </div>

      {/* Tabs */}
      <div className={styles.tabBar}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`${styles.tabBtn} ${activeTab === tab.id ? styles.activeTab : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className={styles.tabContent}>
        {activeTab === 'overview' && (
          <div className={styles.overviewGrid}>
            <div className={styles.statBox}>
              <span className={styles.statNum}>{cases?.length ?? 0}</span>
              <span className={styles.statLabel}>Handover Cases</span>
            </div>
            <div className={styles.statBox}>
              <span className={styles.statNum}>{sources?.length ?? 0}</span>
              <span className={styles.statLabel}>Connected Sources</span>
            </div>
            <div className={styles.statBox}>
              <span className={styles.statNum}>{members?.length ?? 0}</span>
              <span className={styles.statLabel}>Team Members</span>
            </div>
          </div>
        )}

        {activeTab === 'cases' && (
          <div className={styles.casesTab}>
            <div className={styles.tabSectionHeader}>
              <h3>Handover Cases</h3>
              <Link to={`/projects/${projectId}/cases/new`} className={styles.secondaryBtn}>
                <Plus size={14} /> New Case
              </Link>
            </div>

            {cases && cases.length > 0 ? (
              <div className={styles.casesList}>
                {cases.map((c) => (
                  <Link key={c.id} to={`/cases/${c.id}`} className={styles.caseItem}>
                    <div className={styles.caseItemLeft}>
                      <span className={styles.caseNumber}>#{c.case_number}</span>
                      <div>
                        <h4 className={styles.caseTitle}>{c.title}</h4>
                        <span className={styles.caseMeta}>
                          {c.transition_type.replace(/_/g, ' ')}
                        </span>
                      </div>
                    </div>

                    <div className={styles.caseItemRight}>
                      {c.is_blocked && (
                        <span className={styles.blockedBadge}>
                          <AlertTriangle size={12} /> Blocked
                        </span>
                      )}
                      <span className={styles.statusBadge}>{c.status}</span>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className={styles.emptyTab}>
                <FileStack size={32} />
                <p>No handover cases created for this project yet.</p>
                <Link to={`/projects/${projectId}/cases/new`} className={styles.secondaryBtn}>
                  <Plus size={14} /> Create First Case
                </Link>
              </div>
            )}
          </div>
        )}

        {activeTab === 'sources' && (
          <div className={styles.sourcesTab}>
            <div className={styles.tabSectionHeader}>
              <h3>Connected Sources</h3>
              <Link to="/sources" className={styles.secondaryBtn}>
                Manage Sources
              </Link>
            </div>

            {sources && sources.length > 0 ? (
              <div className={styles.sourcesList}>
                {sources.map((s) => (
                  <div key={s.id} className={styles.sourceItem}>
                    <GitBranch size={20} className={styles.sourceIcon} />
                    <div className={styles.sourceInfo}>
                      <h4>{s.name}</h4>
                      <span className={styles.sourceType}>{s.source_type}</span>
                    </div>
                    <span className={styles.connectionBadge}>{s.connection_status}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className={styles.emptyTab}>
                <GitBranch size={32} />
                <p>No sources connected to this project yet.</p>
                <Link to="/sources" className={styles.secondaryBtn}>
                  Connect Source
                </Link>
              </div>
            )}
          </div>
        )}

        {activeTab === 'people' && (
          <div className={styles.peopleTab}>
            <div className={styles.tabSectionHeader}>
              <h3>Project Members</h3>
            </div>

            {members && members.length > 0 ? (
              <div className={styles.membersGrid}>
                {members.map((m) => (
                  <div key={m.id} className={styles.memberCard}>
                    <div className={styles.memberAvatar}>
                      {m.user_display_name ? m.user_display_name[0] : 'U'}
                    </div>
                    <div className={styles.memberDetails}>
                      <h4>{m.user_display_name}</h4>
                      <p>{m.user_email}</p>
                      <span className={styles.roleBadge}>{m.role}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className={styles.emptyTab}>
                <Users size={32} />
                <p>No members found in this project.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
