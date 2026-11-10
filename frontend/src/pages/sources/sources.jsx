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
import styles from './sources.module.css';

export default function SourcesPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef(null);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [importStatusMessage, setImportStatusMessage] = useState('');

  // 1. Fetch workspaces and default project
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

  // 4. Fetch uploaded documents
  const { data: documents, isLoading: docsLoading } = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => documentApi.listDocuments(projectId),
    enabled: !!projectId,
  });

  // Upload Mutation
  const uploadMutation = useMutation({
    mutationFn: (file) => documentApi.uploadDocument(projectId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', projectId] });
      setUploadError('');
      if (fileInputRef.current) fileInputRef.current.value = '';
    },
    onError: (err) => {
      setUploadError(err.data?.error?.message || err.message || 'Upload failed');
    },
  });

  // Import trigger mutation
  const importMutation = useMutation({
    mutationFn: (sourceId) => sourceApi.triggerImport(sourceId),
    onSuccess: (data) => {
      setImportStatusMessage(`Sync triggered: Ingestion worker scanning repository records…`);
      queryClient.invalidateQueries({ queryKey: ['sources', projectId] });
      setTimeout(() => setImportStatusMessage(''), 6000);
    },
  });

  // Stale detection / refresh mutation with modification simulation
  const refreshMutation = useMutation({
    mutationFn: (sourceId) => sourceApi.refreshSource(sourceId, true),
    onSuccess: (data) => {
      setImportStatusMessage(
        `Freshness check complete: ${data.records_checked} records verified. Upstream modification detected — ${data.claims_marked_stale} claim(s) flagged for review.`
      );
      queryClient.invalidateQueries({ queryKey: ['sources', projectId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
      setTimeout(() => setImportStatusMessage(''), 8000);
    },
    onError: (err) => {
      setUploadError(err.data?.detail || err.message || 'Refresh failed');
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
          <RefreshCw size={16} className={styles.spinIcon} />
          <span>{importStatusMessage}</span>
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
            <p>Connect your GitHub App to ingest issues, pull requests, reviews, and commits.</p>
          </div>
          <div className={styles.statusIndicator}>
            {githubStatus?.connected ? (
              <span className={styles.connectedBadge}>
                <CheckCircle2 size={14} /> Connected ({githubStatus.account_login})
              </span>
            ) : (
              <span className={styles.syntheticBadge}>
                Using Synthetic Fixture
              </span>
            )}
          </div>
        </div>

        <div className={styles.cardBody}>
          <div className={styles.cardMetaRow}>
            <div>
              <span className={styles.metaLabel}>Configured Repository</span>
              <span className={styles.metaValue}>{defaultProject?.repo_url || 'https://github.com/acme-eng/atlas-platform'}</span>
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
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button
                          className={styles.importTriggerBtn}
                          onClick={() => importMutation.mutate(src.id)}
                          disabled={importMutation.isPending}
                          title="Trigger full background ingestion"
                        >
                          <RefreshCw size={13} />
                          <span>Sync</span>
                        </button>
                        <button
                          className={styles.importTriggerBtn}
                          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}
                          onClick={() => refreshMutation.mutate(src.id)}
                          disabled={refreshMutation.isPending}
                          title="Check upstream changes and propagate staleness"
                        >
                          <RefreshCw size={13} className={refreshMutation.isPending ? styles.spinIcon : ''} />
                          <span>Check Freshness</span>
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
