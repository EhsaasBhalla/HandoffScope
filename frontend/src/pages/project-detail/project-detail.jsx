import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  FolderKanban,
  FileStack,
  GitBranch,
  Users,
  Plus,
  ExternalLink,
  Calendar,
  AlertTriangle,
  UserCheck,
  CheckCircle2,
  XCircle,
  Sparkles,
  RefreshCw,
} from 'lucide-react';
import { projectApi } from '../../api/project.api';
import { caseApi } from '../../api/case.api';
import { sourceApi } from '../../api/source.api';
import { identityApi } from '../../api/identity.api';
import styles from './project-detail.module.css';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'cases', label: 'Handover Cases' },
  { id: 'sources', label: 'Sources' },
  { id: 'identities', label: 'Identity Mappings' },
  { id: 'people', label: 'People' },
];

export default function ProjectDetailPage() {
  const { projectId } = useParams();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('overview');
  const [selectedUserMap, setSelectedUserMap] = useState({});

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

  // Fetch identity mappings & coverage
  const { data: mappings, isLoading: mappingsLoading } = useQuery({
    queryKey: ['identity-mappings', projectId],
    queryFn: () => identityApi.getMappings(projectId),
    enabled: !!projectId,
  });

  const { data: coverage } = useQuery({
    queryKey: ['identity-coverage', projectId],
    queryFn: () => identityApi.getCoverage(projectId),
    enabled: !!projectId,
  });

  // Auto-suggest mutation
  const autoSuggestMutation = useMutation({
    mutationFn: () => identityApi.autoSuggest(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries(['identity-mappings', projectId]);
      queryClient.invalidateQueries(['identity-coverage', projectId]);
    },
  });

  // Update mapping mutation
  const updateMappingMutation = useMutation({
    mutationFn: ({ id, data }) => identityApi.updateMapping(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['identity-mappings', projectId]);
      queryClient.invalidateQueries(['identity-coverage', projectId]);
    },
  });

  const handleConfirm = (mapping) => {
    const targetUserId = selectedUserMap[mapping.id] || mapping.mapped_user_id;
    if (!targetUserId) return;
    updateMappingMutation.mutate({
      id: mapping.id,
      data: { action: 'confirm', mapped_user_id: targetUserId },
    });
  };

  const handleReject = (mapping) => {
    updateMappingMutation.mutate({
      id: mapping.id,
      data: { action: 'reject' },
    });
  };

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

      {/* Tabs Navigation */}
      <div className={styles.tabBar}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`${styles.tabBtn} ${activeTab === tab.id ? styles.tabBtnActive : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Panels */}
      <div className={styles.tabContent}>
        {activeTab === 'overview' && (
          <div className={styles.overviewGrid}>
            <div className={styles.statsCard}>
              <div className={styles.statsIconWrap}>
                <FileStack size={20} />
              </div>
              <div className={styles.statsContent}>
                <span className={styles.statsLabel}>Handover Cases</span>
                <span className={styles.statsValue}>{cases ? cases.length : 0}</span>
              </div>
            </div>

            <div className={styles.statsCard}>
              <div className={styles.statsIconWrap}>
                <GitBranch size={20} />
              </div>
              <div className={styles.statsContent}>
                <span className={styles.statsLabel}>Connected Sources</span>
                <span className={styles.statsValue}>{sources ? sources.length : 0}</span>
              </div>
            </div>

            <div className={styles.statsCard}>
              <div className={styles.statsIconWrap}>
                <UserCheck size={20} />
              </div>
              <div className={styles.statsContent}>
                <span className={styles.statsLabel}>Identity Coverage</span>
                <span className={styles.statsValue}>
                  {coverage ? `${coverage.coverage_percent}%` : '0%'}
                </span>
              </div>
            </div>

            <div className={styles.statsCard}>
              <div className={styles.statsIconWrap}>
                <Users size={20} />
              </div>
              <div className={styles.statsContent}>
                <span className={styles.statsLabel}>Members</span>
                <span className={styles.statsValue}>{members ? members.length : 0}</span>
              </div>
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
                  <Link
                    key={c.id}
                    to={`/cases/${c.id}`}
                    className={styles.caseCard}
                  >
                    <div className={styles.caseHeader}>
                      <span className={styles.caseNumber}>{c.case_number}</span>
                      <span className={styles.caseStatus}>{c.status}</span>
                    </div>
                    <h4 className={styles.caseTitle}>{c.title}</h4>
                    <p className={styles.caseDescription}>
                      {c.description || 'No description provided.'}
                    </p>
                    <div className={styles.caseMeta}>
                      <div className={styles.metaItem}>
                        <Calendar size={14} />
                        <span>{new Date(c.created_at).toLocaleDateString()}</span>
                      </div>
                      {c.is_blocked && (
                        <div className={styles.blockedBadge}>
                          <AlertTriangle size={12} />
                          <span>Blocked</span>
                        </div>
                      )}
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

        {activeTab === 'identities' && (
          <div className={styles.identityTab}>
            {/* Coverage Banner */}
            <div className={styles.coverageCard}>
              <div className={styles.coverageStatsGrid}>
                <div className={styles.coverageStat}>
                  <span className={styles.coverageNumber}>{coverage?.coverage_percent ?? 0}%</span>
                  <span className={styles.coverageLabel}>Source Records Mapped</span>
                </div>
                <div className={styles.coverageStat}>
                  <span className={styles.coverageNumber}>{coverage?.verified_count ?? 0}</span>
                  <span className={styles.coverageLabel}>Verified</span>
                </div>
                <div className={styles.coverageStat}>
                  <span className={styles.coverageNumber}>{coverage?.suggested_count ?? 0}</span>
                  <span className={styles.coverageLabel}>Suggested</span>
                </div>
                <div className={styles.coverageStat}>
                  <span className={styles.coverageNumber}>{coverage?.unmatched_count ?? 0}</span>
                  <span className={styles.coverageLabel}>Unmatched</span>
                </div>
              </div>

              <button
                className={styles.secondaryBtn}
                onClick={() => autoSuggestMutation.mutate()}
                disabled={autoSuggestMutation.isPending}
              >
                <Sparkles size={14} />
                {autoSuggestMutation.isPending ? 'Auto-Matching…' : 'Run Auto-Match'}
              </button>
            </div>

            {/* Mappings List */}
            {mappingsLoading ? (
              <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--color-text-muted)' }}>
                Loading contributor identities...
              </div>
            ) : mappings && mappings.length > 0 ? (
              <div className={styles.mappingsList}>
                {mappings.map((m) => {
                  const currentSelectedUser = selectedUserMap[m.id] ?? (m.mapped_user_id || '');
                  const isVerified = m.confidence === 'VERIFIED';
                  const isSuggested = m.confidence === 'SUGGESTED';

                  return (
                    <div key={m.id} className={styles.mappingCard}>
                      <div className={styles.mappingLeft}>
                        <div className={styles.contributorAvatar}>
                          {(m.external_username || 'U')[0].toUpperCase()}
                        </div>
                        <div className={styles.mappingMeta}>
                          <span className={styles.authorUsername}>@{m.external_username}</span>
                          <span className={styles.authorStats}>
                            {m.contributions_count} source contribution{m.contributions_count === 1 ? '' : 's'} • Provider: {m.external_provider}
                          </span>
                        </div>
                      </div>

                      <div className={styles.mappingRight}>
                        <span
                          className={`${styles.statusBadge} ${
                            isVerified
                              ? styles.statusVerified
                              : isSuggested
                              ? styles.statusSuggested
                              : styles.statusUnmatched
                          }`}
                        >
                          {m.confidence}
                        </span>

                        <select
                          className={styles.userSelect}
                          value={currentSelectedUser}
                          onChange={(e) =>
                            setSelectedUserMap((prev) => ({
                              ...prev,
                              [m.id]: e.target.value,
                            }))
                          }
                        >
                          <option value="">-- Assign HandoffScope User --</option>
                          {members?.map((mem) => (
                            <option key={mem.user_id} value={mem.user_id}>
                              {mem.user_display_name} ({mem.user_email})
                            </option>
                          ))}
                        </select>

                        <div style={{ display: 'flex', gap: '6px' }}>
                          <button
                            className={styles.confirmBtn}
                            onClick={() => handleConfirm(m)}
                            disabled={!currentSelectedUser || updateMappingMutation.isPending}
                            title="Confirm mapping to user"
                          >
                            <CheckCircle2 size={12} style={{ marginRight: '4px' }} />
                            Confirm
                          </button>
                          {m.mapped_user_id && (
                            <button
                              className={styles.rejectBtn}
                              onClick={() => handleReject(m)}
                              disabled={updateMappingMutation.isPending}
                              title="Reject and unmap"
                            >
                              <XCircle size={12} style={{ marginRight: '4px' }} />
                              Reject
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className={styles.emptyTab}>
                <UserCheck size={32} />
                <p>No external contributors discovered yet.</p>
                <button
                  className={styles.secondaryBtn}
                  onClick={() => autoSuggestMutation.mutate()}
                >
                  <Sparkles size={14} /> Scan Source Records
                </button>
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
