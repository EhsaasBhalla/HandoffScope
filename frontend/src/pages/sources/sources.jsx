import { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  GitBranch,
  Upload,
  FileText,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  ExternalLink,
  Plus,
} from 'lucide-react';
import { projectApi } from '../../api/project.api';
import { sourceApi, githubApi } from '../../api/source.api';
import { documentApi } from '../../api/document.api';
import { jobApi } from '../../api/job.api';
import styles from './sources.module.css';

export default function SourcesPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef(null);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [importStatusMessage, setImportStatusMessage] = useState('');
  const [importError, setImportError] = useState('');
  const [syncingSourceId, setSyncingSourceId] = useState(null);
  const [showAddRepo, setShowAddRepo] = useState(false);
  const [repoSlugInput, setRepoSlugInput] = useState('');

  // 1. Fetch workspaces and active project
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

  const defaultProject = projects?.[0];
  const projectId = selectedProjectId || defaultProject?.id;
  const activeProject = projects?.find((p) => p.id === projectId) || defaultProject;

  // 2. Fetch GitHub connection status
  const { data: githubStatus } = useQuery({
    queryKey: ['github-status', activeWsId],
    queryFn: () => githubApi.getStatus(activeWsId),
    enabled: !!activeWsId,
  });

  // 3. Fetch connected sources
  const { data: sources, isLoading: sourcesLoading } = useQuery({
    queryKey: ['sources', projectId],
    queryFn: () => sourceApi.listSources(projectId),
    enabled: !!projectId,
  });

  // 4. Fetch uploaded documents (poll every 2s while any document is PENDING/RUNNING)
  const { data: documents } = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => documentApi.listDocuments(projectId),
    enabled: !!projectId,
    refetchInterval: (query) => {
      const list = query.state.data;
      if (Array.isArray(list) && list.some((d) => d.processing_status === 'PENDING' || d.processing_status === 'RUNNING')) {
        return 2000;
      }
      return false;
    },
  });

  // Connect GitHub repo mutation
  const connectRepoMutation = useMutation({
    mutationFn: (repoSlug) => {
      const cleaned = repoSlug.trim().replace(/^https?:\/\/github\.com\//, '').replace(/\.git$/, '').replace(/^\/+|\/+$/g, '');
      const [owner, repo] = cleaned.split('/');
      if (!owner || !repo) {
        throw new Error('Enter repository in "owner/repo" format (e.g. pydantic/pydantic)');
      }
      return sourceApi.connectSource(projectId, {
        source_type: 'GITHUB_REPO',
        name: `${owner}/${repo}`,
        external_id: `${owner}/${repo}`,
        config: { owner, repo },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources', projectId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      setRepoSlugInput('');
      setShowAddRepo(false);
      setImportError('');
    },
    onError: (err) => {
      setImportError(err.data?.detail || err.message || 'Failed to connect repository');
    },
  });

  // Upload Mutation
  const uploadMutation = useMutation({
    mutationFn: (file) => documentApi.uploadDocument(projectId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', projectId] });
      queryClient.invalidateQueries({ queryKey: ['sources', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project-timeline', projectId] });
      setUploadError('');
      if (fileInputRef.current) fileInputRef.current.value = '';
    },
    onError: (err) => {
      setUploadError(err.data?.detail || err.data?.error?.message || err.message || 'Upload failed');
    },
  });

  // Poll background sync job until completion or failure
  async function pollSyncJob(jobId) {
    for (let attempt = 0; attempt < 45; attempt++) {
      await new Promise((r) => setTimeout(r, 1200));
      try {
        const job = await jobApi.getJob(jobId);
        if (job.status === 'COMPLETED') {
          setSyncingSourceId(null);
          setImportStatusMessage(`Sync completed successfully! Source records & commit history updated.`);
          queryClient.invalidateQueries({ queryKey: ['sources', projectId] });
          queryClient.invalidateQueries({ queryKey: ['project-timeline', projectId] });
          queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
          setTimeout(() => setImportStatusMessage(''), 8000);
          return;
        }
        if (job.status === 'FAILED' || job.status === 'CANCELLED') {
          setSyncingSourceId(null);
          setImportStatusMessage('');
          setImportError(`Sync failed: ${job.error_message || 'Unknown error'}`);
          queryClient.invalidateQueries({ queryKey: ['sources', projectId] });
          return;
        }
        setImportStatusMessage(`Syncing repository… ${job.progress_message || job.status}`);
      } catch (pollErr) {
        console.warn('Job poll error:', pollErr);
      }
    }
    setSyncingSourceId(null);
    setImportStatusMessage('Sync is still running in background — refresh shortly to check updated records.');
  }

  // Import trigger mutation
  const importMutation = useMutation({
    mutationFn: (sourceId) => sourceApi.triggerImport(sourceId),
    onMutate: (sourceId) => {
      setImportError('');
      setSyncingSourceId(sourceId);
      setImportStatusMessage('Enqueuing background sync job…');
    },
    onSuccess: (data) => {
      if (data?.job_id) {
        setImportStatusMessage(`Sync started (Job ${data.job_id.slice(0, 8)}): fetching issues, PRs & commits…`);
        pollSyncJob(data.job_id);
      }
      queryClient.invalidateQueries({ queryKey: ['sources', projectId] });
    },
    onError: (err) => {
      setSyncingSourceId(null);
      setImportStatusMessage('');
      setImportError(err.data?.detail || err.message || 'Failed to trigger sync');
    },
  });

  // Stale detection / refresh mutation
  const refreshMutation = useMutation({
    mutationFn: ({ sourceId, simulate }) => sourceApi.refreshSource(sourceId, simulate),
    onSuccess: (data) => {
      setImportError('');
      const msg = data.records_changed > 0
        ? `Freshness check complete: ${data.records_checked} records checked. Upstream modification detected (${data.records_changed} changed) — ${data.claims_marked_stale} claim(s) flagged for review.`
        : `Freshness check complete: ${data.records_checked} records verified. Everything is current with zero drift.`;
      setImportStatusMessage(msg);
      queryClient.invalidateQueries({ queryKey: ['sources', projectId] });
      queryClient.invalidateQueries({ queryKey: ['case'] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['case-claims'] });
      queryClient.invalidateQueries({ queryKey: ['project-timeline', projectId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      setTimeout(() => setImportStatusMessage(''), 8000);
    },
    onError: (err) => {
      setImportError(err.data?.detail || err.message || 'Refresh failed');
    },
  });

  function handleFileSelect(e) {
    const file = e.target.files?.[0];
    if (file) {
      setUploadError('');
      uploadMutation.mutate(file);
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h2>Sources & Ingestion</h2>
          <p className={styles.subtitle}>
            Connect GitHub repositories, upload documentation, and manage the project's evidence foundation.
          </p>
        </div>
        {projects && projects.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>Project:</span>
            <select
              value={projectId || ''}
              onChange={(e) => setSelectedProjectId(e.target.value)}
              style={{
                padding: '6px 12px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--color-border)',
                background: 'var(--color-surface)',
                color: 'var(--color-text)',
                fontWeight: 600,
                fontSize: 'var(--text-sm)',
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

      {importStatusMessage && (
        <div className={styles.statusBanner}>
          <RefreshCw size={16} className={syncingSourceId ? styles.spinIcon : ''} />
          <span>{importStatusMessage}</span>
        </div>
      )}

      {importError && (
        <div className={styles.errorBox} style={{ marginBottom: 'var(--space-md)' }}>
          {importError}
        </div>
      )}

      {/* GitHub Integration Card */}
      <div className={styles.card}>
        <div className={styles.cardTop}>
          <div className={styles.sourceLogo}>
            <GitBranch size={24} />
          </div>
          <div className={styles.cardHeaderInfo}>
            <h3>GitHub Integration</h3>
            <p>Connect any public or app-authorized repository to ingest issues, pull requests, reviews, and commits.</p>
          </div>
          <div className={styles.statusIndicator}>
            <button
              className={styles.importTriggerBtn}
              onClick={() => setShowAddRepo((v) => !v)}
            >
              <Plus size={14} />
              <span>Connect Repo</span>
            </button>
            {githubStatus?.connected ? (
              <span className={styles.connectedBadge}>
                <CheckCircle2 size={14} /> Connected ({githubStatus.account_login})
              </span>
            ) : (
              <span className={styles.syntheticBadge}>
                Public Repo &amp; Synthetic Fixture
              </span>
            )}
          </div>
        </div>

        {showAddRepo && (
          <div style={{ padding: 'var(--space-md) var(--space-lg)', borderTop: '1px solid var(--color-border-subtle)', display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              type="text"
              placeholder="owner/repo or https://github.com/owner/repo"
              value={repoSlugInput}
              onChange={(e) => setRepoSlugInput(e.target.value)}
              style={{ flex: 1, minWidth: '240px', padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--color-border)', background: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', fontSize: 'var(--text-sm)' }}
            />
            <button
              className={styles.importTriggerBtn}
              disabled={!repoSlugInput.trim() || connectRepoMutation.isPending}
              onClick={() => connectRepoMutation.mutate(repoSlugInput)}
            >
              {connectRepoMutation.isPending ? 'Connecting…' : 'Save Source'}
            </button>
          </div>
        )}

        <div className={styles.cardBody}>
          <div className={styles.cardMetaRow}>
            <div>
              <span className={styles.metaLabel}>Configured Repository</span>
              <span className={styles.metaValue}>{activeProject?.repo_url || 'No repository URL configured'}</span>
            </div>
            <div>
              <span className={styles.metaLabel}>Permissions</span>
              <span className={styles.metaValue}>Issues (Read), Pull Requests (Read), Contents (Read)</span>
            </div>
          </div>
        </div>
      </div>

      {/* Document Upload Area */}
      <div className={styles.card}>
        <div className={styles.cardTop}>
          <div className={styles.sourceLogo}>
            <Upload size={24} />
          </div>
          <div className={styles.cardHeaderInfo}>
            <h3>Document Upload</h3>
            <p>Upload architecture specs, runbooks, RFCs, or onboarding notes (PDF, DOCX, MD, TXT up to 50MB).</p>
          </div>
        </div>

        <div className={styles.uploadZone}>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileSelect}
            accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
            style={{ display: 'none' }}
            id="doc-upload-input"
          />
          <label htmlFor="doc-upload-input" className={styles.uploadDropArea}>
            <Upload size={32} className={styles.uploadIcon} />
            <span className={styles.uploadPrompt}>
              {uploadMutation.isPending ? 'Uploading & parsing document…' : 'Click to select or drag and drop a file'}
            </span>
            <span className={styles.uploadHint}>Supported formats: PDF, DOCX, Markdown, Plain Text</span>
          </label>

          {uploadError && <div className={styles.errorBox}>{uploadError}</div>}
        </div>

        {/* Uploaded Documents List */}
        {documents && documents.length > 0 && (
          <div className={styles.docsList}>
            <h4 className={styles.subHeading}>Uploaded Documents ({documents.length})</h4>
            <div className={styles.docsTableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Type</th>
                    <th>Size</th>
                    <th>Pages / Sections</th>
                    <th>Status</th>
                    <th>Uploaded</th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((doc) => (
                    <tr key={doc.id}>
                      <td className={styles.docNameCell}>
                        <FileText size={16} />
                        <span>{doc.original_filename}</span>
                      </td>
                      <td className={styles.monoCell}>{doc.mime_type.split('/').pop()}</td>
                      <td>{(doc.file_size / 1024).toFixed(1)} KB</td>
                      <td>{doc.page_count ? `${doc.page_count} pages` : doc.section_count ? `${doc.section_count} sections` : '—'}</td>
                      <td>
                        <span className={`${styles.statusChip} ${styles[doc.processing_status.toLowerCase()] || ''}`}>
                          {doc.processing_status}
                        </span>
                      </td>
                      <td className={styles.dateCell}>{new Date(doc.created_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Connected Source Inventory */}
      <div className={styles.card}>
        <div className={styles.cardTop}>
          <div className={styles.cardHeaderInfo}>
            <h3>Source Inventory</h3>
            <p>All connected data streams feeding into the knowledge reconstruction pipeline.</p>
          </div>
        </div>

        {sourcesLoading ? (
          <div className={styles.loading}>Loading sources…</div>
        ) : sources && sources.length > 0 ? (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Source Name</th>
                  <th>Type</th>
                  <th>External ID</th>
                  <th>Connection Status</th>
                  <th>Connected Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((src) => (
                  <tr key={src.id}>
                    <td className={styles.boldCell}>{src.name}</td>
                    <td className={styles.monoCell}>{src.source_type}</td>
                    <td className={styles.monoCell}>{src.external_id || '—'}</td>
                    <td>
                      <span className={styles.activeStatusBadge}>{src.connection_status}</span>
                    </td>
                    <td>{new Date(src.created_at).toLocaleDateString()}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                        <button
                          className={styles.importTriggerBtn}
                          onClick={() => importMutation.mutate(src.id)}
                          disabled={syncingSourceId === src.id || importMutation.isPending}
                          title="Trigger background ingestion from source"
                        >
                          <RefreshCw size={13} className={syncingSourceId === src.id ? styles.spinIcon : ''} />
                          <span>{syncingSourceId === src.id ? 'Syncing…' : 'Sync'}</span>
                        </button>
                        <button
                          className={styles.importTriggerBtn}
                          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}
                          onClick={() => refreshMutation.mutate({ sourceId: src.id, simulate: false })}
                          disabled={refreshMutation.isPending}
                          title="Check upstream changes against last sync"
                        >
                          <RefreshCw size={13} className={refreshMutation.isPending ? styles.spinIcon : ''} />
                          <span>Check Freshness</span>
                        </button>
                        <button
                          className={styles.importTriggerBtn}
                          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-muted)' }}
                          onClick={() => refreshMutation.mutate({ sourceId: src.id, simulate: true })}
                          disabled={refreshMutation.isPending}
                          title="Simulate an upstream edit to test staleness drift propagation"
                        >
                          <span>Simulate Drift</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className={styles.emptySources}>
            <p>No external sources connected yet.</p>
          </div>
        )}
      </div>
    </div>
  );
}
