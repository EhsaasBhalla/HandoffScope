import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  GitCommit,
  GitPullRequest,
  AlertCircle,
  ShieldCheck,
  Search,
  ExternalLink,
  Calendar,
  CheckCircle2,
  FolderKanban,
  MessageSquare,
  FileText,
  X,
} from 'lucide-react';
import { projectApi } from '../../api/project.api';
import { timelineApi } from '../../api/timeline.api';
import styles from './timeline.module.css';

export default function TimelinePage() {
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [selectedType, setSelectedType] = useState('ALL');
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);

  // Debounce search input to avoid request flooding
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // 1. Fetch workspaces & projects
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

  // Effective project ID (default to first project)
  const effectiveProjectId = selectedProjectId || (Array.isArray(projects) ? projects[0]?.id : undefined);

  // 2. Fetch timeline
  const { data: timelineData, isLoading: timelineLoading } = useQuery({
    queryKey: ['project-timeline', effectiveProjectId, selectedType, debouncedSearch, page],
    queryFn: () =>
      timelineApi.getTimeline(effectiveProjectId, {
        event_type: selectedType === 'ALL' ? undefined : selectedType,
        search: debouncedSearch || undefined,
        page,
        per_page: 25,
      }),
    enabled: !!effectiveProjectId,
  });

  const items = Array.isArray(timelineData?.items) ? timelineData.items : [];
  const eventTypes = Array.isArray(timelineData?.event_types) ? timelineData.event_types : [];
  const total = timelineData?.total || 0;
  const totalPages = timelineData?.total_pages || 1;

  // Icon mapping
  const renderNodeIcon = (type) => {
    switch (type.toUpperCase()) {
      case 'COMMIT':
        return (
          <div className={`${styles.nodeIcon} ${styles.nodeCommit}`}>
            <GitCommit size={15} />
          </div>
        );
      case 'PULL_REQUEST':
        return (
          <div className={`${styles.nodeIcon} ${styles.nodePR}`}>
            <GitPullRequest size={15} />
          </div>
        );
      case 'ISSUE':
        return (
          <div className={`${styles.nodeIcon} ${styles.nodeIssue}`}>
            <AlertCircle size={15} />
          </div>
        );
      case 'AUDIT':
        return (
          <div className={`${styles.nodeIcon} ${styles.nodeAudit}`}>
            <ShieldCheck size={15} />
          </div>
        );
      case 'SOURCE_COMMENT':
      case 'SOURCE_REVIEW':
        return (
          <div className={`${styles.nodeIcon} ${styles.nodePR}`}>
            <MessageSquare size={15} />
          </div>
        );
      case 'DOCUMENT':
        return (
          <div className={`${styles.nodeIcon} ${styles.nodeDefault}`}>
            <FileText size={15} />
          </div>
        );
      default:
        return (
          <div className={`${styles.nodeIcon} ${styles.nodeDefault}`}>
            <GitCommit size={15} />
          </div>
        );
    }
  };

  const getBadgeClass = (type) => {
    switch (type.toUpperCase()) {
      case 'COMMIT':
        return styles.badgeCommit;
      case 'PULL_REQUEST':
        return styles.badgePR;
      case 'ISSUE':
        return styles.badgeIssue;
      case 'AUDIT':
        return styles.badgeAudit;
      default:
        return styles.badgeDefault;
    }
  };

  const formatDate = (isoStr) => {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoStr;
    }
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <div className={styles.titleRow}>
            <h2>Source & Audit Timeline</h2>
          </div>
          <p className={styles.subtitle}>
            Chronological stream reconstructing commits, pull requests, issues, comments, and audit governance actions.
          </p>
        </div>

        {/* Project Selector */}
        {Array.isArray(projects) && projects.length > 0 && (
          <div className={styles.projectSelectWrap}>
            <FolderKanban size={15} color="var(--color-text-muted)" />
            <span className={styles.projectSelectLabel}>Project:</span>
            <select
              className={styles.projectSelect}
              value={effectiveProjectId}
              onChange={(e) => {
                setSelectedProjectId(e.target.value);
                setPage(1);
              }}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarTop}>
          {/* Search Box */}
          <div className={styles.searchBox}>
            <Search size={14} className={styles.searchIcon} />
            <input
              type="text"
              placeholder="Search title, commit messages, or summary..."
              className={styles.searchInput}
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
            {searchInput && (
              <button
                className={styles.clearSearchBtn}
                onClick={() => setSearchInput('')}
                title="Clear search"
              >
                <X size={12} />
              </button>
            )}
          </div>

          {/* Filter Chips */}
          <div className={styles.filterChips}>
            <button
              className={`${styles.filterChip} ${selectedType === 'ALL' ? styles.filterChipActive : ''}`}
              onClick={() => {
                setSelectedType('ALL');
                setPage(1);
              }}
            >
              All Events
            </button>
            <button
              className={`${styles.filterChip} ${selectedType === 'COMMIT' ? styles.filterChipActive : ''}`}
              onClick={() => {
                setSelectedType('COMMIT');
                setPage(1);
              }}
            >
              Commits
            </button>
            <button
              className={`${styles.filterChip} ${selectedType === 'PULL_REQUEST' ? styles.filterChipActive : ''}`}
              onClick={() => {
                setSelectedType('PULL_REQUEST');
                setPage(1);
              }}
            >
              Pull Requests
            </button>
            <button
              className={`${styles.filterChip} ${selectedType === 'ISSUE' ? styles.filterChipActive : ''}`}
              onClick={() => {
                setSelectedType('ISSUE');
                setPage(1);
              }}
            >
              Issues
            </button>
            <button
              className={`${styles.filterChip} ${selectedType === 'AUDIT' ? styles.filterChipActive : ''}`}
              onClick={() => {
                setSelectedType('AUDIT');
                setPage(1);
              }}
            >
              Audit Actions
            </button>
          </div>
        </div>

        <div className={styles.statsBar}>
          <span>Showing {items.length} of {total} events</span>
          <span>Sorted chronologically (newest first)</span>
        </div>
      </div>

      {/* Timeline Stream */}
      {timelineLoading ? (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--color-text-muted)' }}>
          Loading chronological timeline...
        </div>
      ) : items.length === 0 ? (
        <div className={styles.emptyState}>
          <Calendar size={32} />
          <h3>No events match the selected filters</h3>
          <p>Try clearing your search query or selecting &ldquo;All Events&rdquo;.</p>
          {(selectedType !== 'ALL' || searchInput) && (
            <button
              className={styles.resetFiltersBtn}
              onClick={() => {
                setSelectedType('ALL');
                setSearchInput('');
                setPage(1);
              }}
            >
              Reset Filters
            </button>
          )}
        </div>
      ) : (
        <div className={styles.streamWrapper}>
          <div className={styles.streamLine} />
          <div className={styles.timelineList}>
            {items.map((item) => {
              const state = item.metadata?.state;
              return (
                <div key={item.id} className={styles.timelineItem}>
                  {renderNodeIcon(item.event_type)}

                  <div className={styles.card}>
                    <div className={styles.cardHeader}>
                      <div className={styles.cardMeta}>
                        <span className={`${styles.typeBadge} ${getBadgeClass(item.event_type)}`}>
                          {item.event_type.replace('SOURCE_', '')}
                        </span>
                        {item.source_name && (
                          <span className={styles.sourcePill}>{item.source_name}</span>
                        )}
                        {state && (
                          <span
                            className={`${styles.stateTag} ${
                              state === 'merged'
                                ? styles.stateMerged
                                : state === 'closed'
                                ? styles.stateClosed
                                : styles.stateOpen
                            }`}
                          >
                            {state}
                          </span>
                        )}
                      </div>
                      <span className={styles.timePill}>{formatDate(item.timestamp)}</span>
                    </div>

                    <div className={styles.cardTitleRow}>
                      <h4 className={styles.cardTitle}>{item.title}</h4>
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                          className={styles.externalLink}
                          title="Open source URL"
                        >
                          <ExternalLink size={13} />
                        </a>
                      )}
                    </div>

                    {item.summary && (
                      <div className={styles.cardBody}>
                        {item.summary.length > 320
                          ? `${item.summary.slice(0, 320)}...`
                          : item.summary}
                      </div>
                    )}

                    <div className={styles.cardFooter}>
                      <div className={styles.actorInfo}>
                        <div className={styles.avatarCircle}>
                          {((item.actor_name || item.actor_external_id || 'U')[0] || 'U').toUpperCase()}
                        </div>
                        <span className={styles.actorName}>
                          {item.actor_name || item.actor_external_id || 'System'}
                        </span>
                        {item.actor_external_id && item.actor_name && (
                          <span className={styles.actorHandle}>@{item.actor_external_id}</span>
                        )}
                        {item.actor_mapped_user_name && (
                          <span className={styles.mappedBadge} title={`Mapped to HandoffScope user ${item.actor_mapped_user_name}`}>
                            <CheckCircle2 size={10} />
                            {item.actor_mapped_user_name}
                          </span>
                        )}
                      </div>

                      {item.metadata?.external_id && (
                        <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
                          Ref #{item.metadata.external_id}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            Previous
          </button>
          <span className={styles.pageText}>
            Page {page} of {totalPages}
          </span>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
