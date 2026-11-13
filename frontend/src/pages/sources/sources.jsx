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
  const [connectorTab, setConnectorTab] = useState('GITHUB_REPO');
  const [repoSlugInput, setRepoSlugInput] = useState('');
  const [gitlabPath, setGitlabPath] = useState('');
  const [gitlabBaseUrl, setGitlabBaseUrl] = useState('https://gitlab.com');
  const [gitlabToken, setGitlabToken] = useState('');
  const [linearTeamKey, setLinearTeamKey] = useState('');
  const [linearToken, setLinearToken] = useState('');
  const [jiraSiteUrl, setJiraSiteUrl] = useState('');
  const [jiraProjectKey, setJiraProjectKey] = useState('');
  const [jiraEmail, setJiraEmail] = useState('');
  const [jiraToken, setJiraToken] = useState('');

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

  // Connect VCS / Tracker source mutation (GitHub, GitLab, Linear, Jira)
  const connectRepoMutation = useMutation({
    mutationFn: () => {
      if (connectorTab === 'GITHUB_REPO') {
        const cleaned = repoSlugInput.trim().replace(/^https?:\/\/github\.com\//, '').replace(/\.git$/, '').replace(/^\/+|\/+$/g, '');
        const [owner, repo] = cleaned.split('/');
        if (!owner || !repo) {
          throw new Error('Enter GitHub repository in "owner/repo" format (e.g. pydantic/pydantic)');
        }
        return sourceApi.connectSource(projectId, {
          source_type: 'GITHUB_REPO',
          name: `${owner}/${repo}`,
          external_id: `${owner}/${repo}`,
          config: { owner, repo },
        });
      }
      if (connectorTab === 'GITLAB_REPO') {
        const cleanPath = gitlabPath.trim().replace(/^https?:\/\/gitlab\.com\//, '').replace(/\.git$/, '').replace(/^\/+|\/+$/g, '');
        if (!cleanPath.includes('/')) {
          throw new Error('Enter GitLab path as "group/project"');
        }
        return sourceApi.connectSource(projectId, {
          source_type: 'GITLAB_REPO',
          name: cleanPath,
          external_id: cleanPath,
          config: {
            project_path: cleanPath,
            base_url: gitlabBaseUrl.trim() || 'https://gitlab.com',
            ...(gitlabToken.trim() ? { private_token: gitlabToken.trim() } : {}),
          },
        });
      }
      if (connectorTab === 'LINEAR_TEAM') {
        const tk = linearTeamKey.trim().toUpperCase();
        if (!tk || !linearToken.trim()) {
          throw new Error('Linear Team Key and API key / OAuth token are required');
        }
        return sourceApi.connectSource(projectId, {
          source_type: 'LINEAR_TEAM',
          name: `Linear Team ${tk}`,
          external_id: tk,
          config: { team_key: tk, access_token: linearToken.trim() },
        });
      }
      if (connectorTab === 'JIRA_PROJECT') {
        const site = jiraSiteUrl.trim().replace(/\/+$/, '');
        const pkey = jiraProjectKey.trim().toUpperCase();
        if (!site.startsWith('https://') || !pkey || !jiraEmail.trim() || !jiraToken.trim()) {
          throw new Error('Jira requires https:// site URL, project key, email, and API token');
        }
        return sourceApi.connectSource(projectId, {
          source_type: 'JIRA_PROJECT',
          name: `Jira ${pkey}`,
          external_id: `${site}/${pkey}`,
          config: { site_url: site, project_key: pkey, email: jiraEmail.trim(), api_token: jiraToken.trim() },
        });
      }
      throw new Error('Unsupported source provider');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources', projectId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      setRepoSlugInput('');
      setGitlabPath('');
      setGitlabToken('');
      setLinearTeamKey('');
      setLinearToken('');
      setJiraSiteUrl('');
      setJiraProjectKey('');
      setJiraEmail('');
      setJiraToken('');
      setShowAddRepo(false);
      setImportError('');
    },
    onError: (err) => {
      setImportError(err.data?.detail || err.message || 'Failed to connect source');
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

  // Local timestamp freshness evaluation mutation (zero remote GitHub calls)
  const refreshMutation = useMutation({
    mutationFn: ({ sourceId, simulate }) => sourceApi.refreshSource(sourceId, simulate),
    onSuccess: (data) => {
      setImportError('');
      const msg = data.records_changed > 0
        ? `Local freshness check complete (${data.records_checked} imported records checked locally; no GitHub call): ${data.records_changed} local timestamp change(s) detected — ${data.claims_marked_stale} claim(s) flagged stale.`
        : `Local freshness check complete (${data.records_checked} imported records checked locally; no GitHub call): all imported records match current baselines.`;
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
            <h3>Multi-Platform VCS &amp; Issue Tracker Integrations</h3>
            <p>Connect GitHub repositories (with code-tree indexing), GitLab projects, Linear teams, or Jira Cloud projects.</p>
          </div>
          <div className={styles.statusIndicator}>
            <button
              className={styles.importTriggerBtn}
              onClick={() => setShowAddRepo((v) => !v)}
            >
              <Plus size={14} />
              <span>Connect Source</span>
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
          <div style={{ padding: 'var(--space-md) var(--space-lg)', borderTop: '1px solid var(--color-border-subtle)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {[
                { id: 'GITHUB_REPO', label: 'GitHub Repo' },
                { id: 'GITLAB_REPO', label: 'GitLab Repo' },
                { id: 'LINEAR_TEAM', label: 'Linear Team' },
                { id: 'JIRA_PROJECT', label: 'Jira Cloud Project' },
              ].map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setConnectorTab(t.id)}
                  style={{
                    padding: '5px 10px',
                    borderRadius: 'var(--radius-md)',
                    fontSize: 'var(--text-xs)',
                    fontWeight: 600,
                    border: `1px solid ${connectorTab === t.id ? 'var(--color-accent)' : 'var(--color-border)'}`,
                    backgroundColor: connectorTab === t.id ? 'var(--color-accent-subtle)' : 'var(--color-bg-primary)',
                    color: connectorTab === t.id ? 'var(--color-accent-text)' : 'var(--color-text-secondary)',
                  }}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {connectorTab === 'GITHUB_REPO' && (
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <input
                  type="text"
                  placeholder="owner/repo or https://github.com/owner/repo"
                  value={repoSlugInput}
                  onChange={(e) => setRepoSlugInput(e.target.value)}
                  style={{ flex: 1, minWidth: '240px' }}
                />
                <button
                  className={styles.importTriggerBtn}
                  disabled={!repoSlugInput.trim() || connectRepoMutation.isPending}
                  onClick={() => connectRepoMutation.mutate()}
                >
                  {connectRepoMutation.isPending ? 'Connecting…' : 'Save GitHub Source'}
                </button>
              </div>
            )}

            {connectorTab === 'GITLAB_REPO' && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '8px', alignItems: 'center' }}>
                <input
                  type="text"
                  placeholder="group/project (e.g. gitlab-org/gitlab-foss)"
                  value={gitlabPath}
                  onChange={(e) => setGitlabPath(e.target.value)}
                />
                <input
                  type="url"
                  placeholder="Base URL (https://gitlab.com)"
                  value={gitlabBaseUrl}
                  onChange={(e) => setGitlabBaseUrl(e.target.value)}
                />
                <input
                  type="password"
                  placeholder="Private Token (optional for public repos)"
                  value={gitlabToken}
                  onChange={(e) => setGitlabToken(e.target.value)}
                />
                <button
                  className={styles.importTriggerBtn}
                  disabled={!gitlabPath.trim() || connectRepoMutation.isPending}
                  onClick={() => connectRepoMutation.mutate()}
                >
                  {connectRepoMutation.isPending ? 'Connecting…' : 'Save GitLab Source'}
                </button>
              </div>
            )}

            {connectorTab === 'LINEAR_TEAM' && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '8px', alignItems: 'center' }}>
                <input
                  type="text"
                  placeholder="Team Key (e.g. ENG)"
                  value={linearTeamKey}
                  onChange={(e) => setLinearTeamKey(e.target.value)}
                />
                <input
                  type="password"
                  placeholder="Linear API Key or OAuth Bearer Token"
                  value={linearToken}
                  onChange={(e) => setLinearToken(e.target.value)}
                />
                <button
                  className={styles.importTriggerBtn}
                  disabled={!linearTeamKey.trim() || !linearToken.trim() || connectRepoMutation.isPending}
                  onClick={() => connectRepoMutation.mutate()}
                >
                  {connectRepoMutation.isPending ? 'Connecting…' : 'Save Linear Source'}
                </button>
              </div>
            )}

            {connectorTab === 'JIRA_PROJECT' && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px', alignItems: 'center' }}>
                <input
                  type="url"
                  placeholder="https://your-org.atlassian.net"
                  value={jiraSiteUrl}
                  onChange={(e) => setJiraSiteUrl(e.target.value)}
                />
                <input
                  type="text"
                  placeholder="Project Key (e.g. PLAT)"
                  value={jiraProjectKey}
                  onChange={(e) => setJiraProjectKey(e.target.value)}
                />
                <input
                  type="email"
                  placeholder="Atlassian Account Email"
                  value={jiraEmail}
                  onChange={(e) => setJiraEmail(e.target.value)}
                />
                <input
                  type="password"
                  placeholder="Jira API Token (stored encrypted)"
                  value={jiraToken}
                  onChange={(e) => setJiraToken(e.target.value)}
                />
                <button
                  className={styles.importTriggerBtn}
                  disabled={!jiraSiteUrl.trim() || !jiraProjectKey.trim() || !jiraEmail.trim() || !jiraToken.trim() || connectRepoMutation.isPending}
                  onClick={() => connectRepoMutation.mutate()}
                >
                  {connectRepoMutation.isPending ? 'Connecting…' : 'Save Jira Source'}
                </button>
              </div>
            )}
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
            <p>
              <strong>Sync Repository</strong> fetches remote updates from GitHub.{' '}
              <strong>Check Local Freshness</strong> evaluates timestamps of already-imported local records only (makes no remote GitHub call).
            </p>
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
                  <th>Status & Sync Telemetry</th>
                  <th>Connected Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((src) => {
                  const run = src.last_sync_run;
                  const lastAttemptTs = run?.completed_at || run?.started_at;
                  return (
                  <tr key={src.id}>
                    <td className={styles.boldCell}>{src.name}</td>
                    <td className={styles.monoCell}>{src.source_type}</td>
                    <td className={styles.monoCell}>{src.external_id || '—'}</td>
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: 'var(--text-xs)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                          <span className={styles.activeStatusBadge}>{src.connection_status}</span>
                          {run && (
                            <span
                              style={{
                                fontWeight: 600,
                                color: run.status === 'FAILED' ? 'var(--color-error)' : run.status === 'PARTIAL' ? 'var(--color-warning)' : 'var(--color-text-secondary)',
                              }}
                            >
                              Last sync: {run.status}
                            </span>
                          )}
                        </div>
                        {src.last_successful_sync_at && (
                          <span style={{ color: 'var(--color-text-muted)' }}>
                            Last successful sync: {new Date(src.last_successful_sync_at).toLocaleString()}
                          </span>
                        )}
                        {lastAttemptTs && (
                          <span style={{ color: 'var(--color-text-muted)' }}>
                            Last attempt: {new Date(lastAttemptTs).toLocaleString()}
                          </span>
                        )}
                        {run && (
                          <span style={{ color: 'var(--color-text-muted)' }}>
                            Counts: fetched {run.records_fetched} · imported {run.records_created} · updated {run.records_updated} · skipped {run.records_skipped ?? 0}
                          </span>
                        )}
                        {(run?.status === 'FAILED' || run?.status === 'PARTIAL') && run?.error_message && (
                          <span style={{ color: run.status === 'FAILED' ? 'var(--color-error)' : 'var(--color-warning)' }}>
                            {run.status === 'PARTIAL' ? 'Partial note: ' : 'Error: '}{run.error_message}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>{new Date(src.created_at).toLocaleDateString()}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                        <button
                          className={styles.importTriggerBtn}
                          onClick={() => importMutation.mutate(src.id)}
                          disabled={syncingSourceId === src.id || importMutation.isPending}
                          title="Fetch remote updates from GitHub via background sync job"
                        >
                          <RefreshCw size={13} className={syncingSourceId === src.id ? styles.spinIcon : ''} />
                          <span>{syncingSourceId === src.id ? 'Syncing…' : 'Sync Repository'}</span>
                        </button>
                        <button
                          className={styles.importTriggerBtn}
                          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}
                          onClick={() => refreshMutation.mutate({ sourceId: src.id, simulate: false })}
                          disabled={refreshMutation.isPending}
                          title="Evaluates age of already-imported local records only; makes zero remote GitHub API calls"
                        >
                          <RefreshCw size={13} className={refreshMutation.isPending ? styles.spinIcon : ''} />
                          <span>Check Local Freshness</span>
                        </button>
                        <button
                          className={styles.importTriggerBtn}
                          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-muted)' }}
                          onClick={() => refreshMutation.mutate({ sourceId: src.id, simulate: true })}
                          disabled={refreshMutation.isPending}
                          title="Simulate an upstream edit on an imported local record to test staleness drift propagation"
                        >
                          <span>Simulate Drift</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                  );
                })}
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
