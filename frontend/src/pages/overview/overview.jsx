import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { FolderKanban, FileStack, GitBranch, Clock } from 'lucide-react';
import { projectApi } from '../../api/project.api';
import { useAuth } from '../../context/AuthContext';
import styles from './overview.module.css';

export default function OverviewPage() {
  const { user } = useAuth();

  const { data: workspaces } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => projectApi.listWorkspaces(),
  });

  const workspaceId = workspaces?.[0]?.id;

  const { data: projects } = useQuery({
    queryKey: ['projects', workspaceId],
    queryFn: () => projectApi.listProjects(workspaceId),
    enabled: !!workspaceId,
  });

  return (
    <div className={styles.page}>
      <div className={styles.greeting}>
        <h2>Welcome back, {user?.display_name?.split(' ')[0]}</h2>
        <p>Here's what's happening across your projects.</p>
      </div>

      <div className={styles.statsGrid}>
        <div className={styles.statCard}>
          <FolderKanban size={24} className={styles.statIcon} />
          <div className={styles.statContent}>
            <span className={styles.statValue}>{projects?.length ?? '—'}</span>
            <span className={styles.statLabel}>Projects</span>
          </div>
        </div>
        <div className={styles.statCard}>
          <FileStack size={24} className={styles.statIcon} />
          <div className={styles.statContent}>
            <span className={styles.statValue}>—</span>
            <span className={styles.statLabel}>Active Cases</span>
          </div>
        </div>
        <div className={styles.statCard}>
          <GitBranch size={24} className={styles.statIcon} />
          <div className={styles.statContent}>
            <span className={styles.statValue}>—</span>
            <span className={styles.statLabel}>Connected Sources</span>
          </div>
        </div>
        <div className={styles.statCard}>
          <Clock size={24} className={styles.statIcon} />
          <div className={styles.statContent}>
            <span className={styles.statValue}>—</span>
            <span className={styles.statLabel}>Pending Reviews</span>
          </div>
        </div>
      </div>

      {workspaces && workspaces.length > 0 && (
        <div className={styles.section}>
          <h3>Workspace</h3>
          <div className={styles.workspaceCard}>
            <h4>{workspaces[0].name}</h4>
            <p>{workspaces[0].description || 'No description'}</p>
          </div>
        </div>
      )}

      {projects && projects.length > 0 && (
        <div className={styles.section}>
          <h3>Projects</h3>
          <div className={styles.projectList}>
            {projects.map((project) => (
              <Link key={project.id} to={`/projects/${project.id}`} className={styles.projectCard}>
                <h4>{project.name}</h4>
                <p>{project.description || 'No description'}</p>
                {project.repo_url && (
                  <span className={styles.repoUrl}>{project.repo_url}</span>
                )}
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
