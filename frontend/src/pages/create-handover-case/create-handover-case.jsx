import { useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, FilePlus } from 'lucide-react';
import { projectApi } from '../../api/project.api';
import { caseApi } from '../../api/case.api';
import styles from './create-handover-case.module.css';

const TRANSITION_TYPES = [
  { value: 'PLANNED_DEPARTURE', label: 'Planned Departure (Standard Handover)' },
  { value: 'UNEXPECTED_UNAVAILABLE', label: 'Unexpected / Sudden Unavailability' },
  { value: 'INTERNAL_TRANSFER', label: 'Internal Team / Project Transfer' },
];

export default function CreateHandoverCasePage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [transitionType, setTransitionType] = useState('PLANNED_DEPARTURE');
  const [departingId, setDepartingId] = useState('');
  const [reviewerId, setReviewerId] = useState('');
  const [recipientId, setRecipientId] = useState('');
  const [scopeStart, setScopeStart] = useState('');
  const [scopeEnd, setScopeEnd] = useState('');
  const [error, setError] = useState('');

  // Fetch project details
  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectApi.getProject(projectId),
    enabled: !!projectId,
  });

  // Fetch project members for participant select
  const { data: members } = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => projectApi.listProjectMembers(projectId),
    enabled: !!projectId,
  });

  const createMutation = useMutation({
    mutationFn: (data) => caseApi.createCase(projectId, data),
    onSuccess: (newCase) => {
      queryClient.invalidateQueries({ queryKey: ['cases', projectId] });
      navigate(`/cases/${newCase.id}`);
    },
    onError: (err) => {
      setError(err.data?.error?.message || err.message || 'Failed to create handover case');
    },
  });

  function handleSubmit(e) {
    e.preventDefault();
    setError('');

    createMutation.mutate({
      title,
      description: description || null,
      transition_type: transitionType,
      departing_id: departingId || null,
      reviewer_id: reviewerId || null,
      recipient_id: recipientId || null,
      scope_start: scopeStart || null,
      scope_end: scopeEnd || null,
    });
  }

  return (
    <div className={styles.container}>
      <Link to={`/projects/${projectId}`} className={styles.backLink}>
        <ArrowLeft size={16} /> Back to {project?.name || 'Project'}
      </Link>

      <div className={styles.header}>
        <div className={styles.iconBox}>
          <FilePlus size={24} />
        </div>
        <div>
          <h2>Create Handover Case</h2>
          <p className={styles.subtitle}>
            Initiate an evidence-led knowledge transition for {project?.name || 'this project'}.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className={styles.card}>
        {error && <div className={styles.errorBox}>{error}</div>}

        <div className={styles.formGroup}>
          <label>Case Title *</label>
          <input
            type="text"
            required
            placeholder="e.g. Arjun Patel — Atlas Platform Handover"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        <div className={styles.formGroup}>
          <label>Transition Type *</label>
          <select
            value={transitionType}
            onChange={(e) => setTransitionType(e.target.value)}
          >
            {TRANSITION_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.grid2}>
          <div className={styles.formGroup}>
            <label>Departing Contributor</label>
            <select
              value={departingId}
              onChange={(e) => setDepartingId(e.target.value)}
            >
              <option value="">Select contributor…</option>
              {members?.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.user_display_name} ({m.user_email})
                </option>
              ))}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label>Designated Successor / Recipient</label>
            <select
              value={recipientId}
              onChange={(e) => setRecipientId(e.target.value)}
            >
              <option value="">Select successor…</option>
              {members?.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.user_display_name} ({m.user_email})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className={styles.grid2}>
          <div className={styles.formGroup}>
            <label>Reviewer</label>
            <select
              value={reviewerId}
              onChange={(e) => setReviewerId(e.target.value)}
            >
              <option value="">Select reviewer…</option>
              {members?.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.user_display_name} ({m.user_email})
                </option>
              ))}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label>Scope Window</label>
            <div className={styles.dateRow}>
              <input
                type="date"
                placeholder="Start"
                value={scopeStart}
                onChange={(e) => setScopeStart(e.target.value)}
              />
              <span className={styles.dateSeparator}>to</span>
              <input
                type="date"
                placeholder="End"
                value={scopeEnd}
                onChange={(e) => setScopeEnd(e.target.value)}
              />
            </div>
          </div>
        </div>

        <div className={styles.formGroup}>
          <label>Scope Summary / Context</label>
          <textarea
            rows={4}
            placeholder="Describe the scope of work, modules, and key responsibilities involved in this transition..."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>

        <div className={styles.actions}>
          <Link to={`/projects/${projectId}`} className={styles.cancelBtn}>
            Cancel
          </Link>
          <button
            type="submit"
            className={styles.submitBtn}
            disabled={createMutation.isPending}
          >
            {createMutation.isPending ? 'Creating Case…' : 'Create Case'}
          </button>
        </div>
      </form>
    </div>
  );
}
