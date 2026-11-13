import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Plus, FolderKanban, GitBranch, Users, ExternalLink } from 'lucide-react';
import { projectApi } from '../../api/project.api';
import styles from './projects.module.css';

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const [selectedWsId, setSelectedWsId] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectSlug, setNewProjectSlug] = useState('');
  const [newProjectDesc, setNewProjectDesc] = useState('');
  const [newProjectRepo, setNewProjectRepo] = useState('');
  const [createError, setCreateError] = useState('');

  // Fetch workspaces
  const { data: workspaces, isLoading: wsLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => projectApi.listWorkspaces(),
  });

  // Default to first workspace
  const activeWsId = selectedWsId || workspaces?.[0]?.id;

  // Fetch projects for selected workspace
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects', activeWsId],
    queryFn: () => projectApi.listProjects(activeWsId),
    enabled: !!activeWsId,
  });

  const createMutation = useMutation({
    mutationFn: (data) => projectApi.createProject(activeWsId, data),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['projects', activeWsId] });
      if (created?.id) {
        queryClient.invalidateQueries({ queryKey: ['sources', created.id] });
      }
      setShowCreateModal(false);
      setNewProjectName('');
      setNewProjectSlug('');
      setNewProjectDesc('');
      setNewProjectRepo('');
      setCreateError('');
    },
    onError: (err) => {
      setCreateError(err.data?.detail || err.data?.error?.message || err.message || 'Failed to create project');
    },
  });

  function handleNameChange(e) {
    const val = e.target.value;
    setNewProjectName(val);
    // Auto-generate slug
    setNewProjectSlug(val.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, ''));
  }

  function handleCreateSubmit(e) {
    e.preventDefault();
    setCreateError('');
    createMutation.mutate({
      name: newProjectName,
      slug: newProjectSlug,
      description: newProjectDesc || null,
      repo_url: newProjectRepo || null,
    });
  }

  return (
    <div className={styles.container}>
      {/* Header with workspace selector and Create Project button */}
      <div className={styles.header}>
        <div>
          <h2>Projects</h2>
          <p className={styles.subtitle}>Select a workspace to manage its engineering projects and handover scopes.</p>
        </div>

        <div className={styles.actions}>
          {workspaces && workspaces.length > 1 && (
            <select
              className={styles.wsSelect}
              value={activeWsId}
              onChange={(e) => setSelectedWsId(e.target.value)}
            >
              {workspaces.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name}
                </option>
              ))}
            </select>
          )}

          <button
            className={styles.createBtn}
            onClick={() => setShowCreateModal(true)}
          >
            <Plus size={16} />
            New Project
          </button>
        </div>
      </div>

      {/* Projects List */}
      {projectsLoading ? (
        <div className={styles.loading}>Loading projects…</div>
      ) : projects && projects.length > 0 ? (
        <div className={styles.grid}>
          {projects.map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`} className={styles.card}>
              <div className={styles.cardHeader}>
                <FolderKanban className={styles.folderIcon} size={22} />
                <span className={styles.projectSlug}>{p.slug}</span>
              </div>
              <h3 className={styles.projectName}>{p.name}</h3>
              <p className={styles.projectDesc}>{p.description || 'No description provided.'}</p>
              {p.repo_url && (
                <div className={styles.repoLink}>
                  <GitBranch size={14} />
                  <span>{p.repo_url.replace('https://github.com/', '')}</span>
                </div>
              )}
            </Link>
          ))}
        </div>
      ) : (
        <div className={styles.empty}>
          <FolderKanban size={40} className={styles.emptyIcon} />
          <h3>No projects yet</h3>
          <p>Get started by creating your first engineering project in this workspace.</p>
          <button className={styles.createBtn} onClick={() => setShowCreateModal(true)}>
            <Plus size={16} /> Create Project
          </button>
        </div>
      )}

      {/* Create Project Modal */}
      {showCreateModal && (
        <div className={styles.modalOverlay} onClick={() => setShowCreateModal(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Create New Project</h3>
              <button className={styles.closeBtn} onClick={() => setShowCreateModal(false)}>✕</button>
            </div>

            <form onSubmit={handleCreateSubmit} className={styles.form}>
              {createError && <div className={styles.error}>{createError}</div>}

              <div className={styles.formGroup}>
                <label>Project Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Atlas Platform"
                  value={newProjectName}
                  onChange={handleNameChange}
                />
              </div>

              <div className={styles.formGroup}>
                <label>Project Slug *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. atlas-platform"
                  value={newProjectSlug}
                  onChange={(e) => setNewProjectSlug(e.target.value)}
                />
              </div>

              <div className={styles.formGroup}>
                <label>Repository URL (optional — auto-connects GitHub source)</label>
                <input
                  type="url"
                  placeholder="https://github.com/org/repo"
                  value={newProjectRepo}
                  onChange={(e) => setNewProjectRepo(e.target.value)}
                />
              </div>

              <div className={styles.formGroup}>
                <label>Description</label>
                <textarea
                  rows={3}
                  placeholder="Summary of this project's role and domain..."
                  value={newProjectDesc}
                  onChange={(e) => setNewProjectDesc(e.target.value)}
                />
              </div>

              <div className={styles.modalFooter}>
                <button
                  type="button"
                  className={styles.cancelBtn}
                  onClick={() => setShowCreateModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className={styles.submitBtn}
                  disabled={createMutation.isPending}
                >
                  {createMutation.isPending ? 'Creating…' : 'Create Project'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
