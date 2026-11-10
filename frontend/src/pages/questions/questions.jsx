import { useState, useEffect } from 'react';
import {
  HelpCircle,
  Plus,
  MessageSquare,
  CheckCircle2,
  XCircle,
  Clock,
  User,
  AlertTriangle,
  ChevronDown,
  RotateCcw,
  Ban,
  FileEdit,
  FolderKanban,
} from 'lucide-react';
import { questionApi } from '../../api/question.api';
import { transferPackApi } from '../../api/transferPack.api';
import { httpClient } from '../../api/httpClient';
import styles from './questions.module.css';

export default function QuestionsPage() {
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('ALL');
  const [answeringId, setAnsweringId] = useState(null);
  const [responseText, setResponseText] = useState('');
  const [isSubmittingAnswer, setIsSubmittingAnswer] = useState(false);

  // Ask Question Modal state
  const [showModal, setShowModal] = useState(false);
  const [cases, setCases] = useState([]);
  const [selectedCaseId, setSelectedCaseId] = useState('');
  const [availablePacks, setAvailablePacks] = useState([]);
  const [selectedPackId, setSelectedPackId] = useState('');
  const [questionText, setQuestionText] = useState('');
  const [whyItMatters, setWhyItMatters] = useState('');
  const [priority, setPriority] = useState('MEDIUM');
  const [isSubmittingQuestion, setIsSubmittingQuestion] = useState(false);

  useEffect(() => {
    loadQuestions();
    loadCases();
  }, [filterStatus]);

  useEffect(() => {
    if (selectedCaseId) {
      loadPacksForCase(selectedCaseId);
    } else {
      setAvailablePacks([]);
      setSelectedPackId('');
    }
  }, [selectedCaseId]);

  async function loadQuestions() {
    setLoading(true);
    try {
      const params = filterStatus !== 'ALL' ? { status: filterStatus } : {};
      const res = await questionApi.listQuestions(params);
      setQuestions(Array.isArray(res) ? res : res?.data || []);
    } catch (err) {
      console.error('Failed to load questions:', err);
    } finally {
      setLoading(false);
    }
  }

  async function loadCases() {
    try {
      const wsRes = await httpClient.get('/api/v1/workspaces');
      if (Array.isArray(wsRes) && wsRes.length > 0) {
        const wsId = wsRes[0].id;
        const pRes = await httpClient.get(`/api/v1/workspaces/${wsId}/projects`);
        const allCases = [];
        if (Array.isArray(pRes)) {
          for (const p of pRes) {
            try {
              const cRes = await httpClient.get(`/api/v1/projects/${p.id}/cases`);
              if (Array.isArray(cRes)) {
                allCases.push(...cRes);
              }
            } catch (_) {}
          }
        }
        setCases(allCases);
        if (allCases.length > 0 && !selectedCaseId) {
          setSelectedCaseId(allCases[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to load cases:', err);
    }
  }

  async function loadPacksForCase(caseId) {
    try {
      const packs = await transferPackApi.listPacks(caseId);
      setAvailablePacks(Array.isArray(packs) ? packs : []);
    } catch (err) {
      console.error('Failed to load packs for case:', err);
      setAvailablePacks([]);
    }
  }

  async function handleCreateQuestion(e) {
    e.preventDefault();
    if (!selectedCaseId || !questionText.trim()) return;

    setIsSubmittingQuestion(true);
    try {
      await questionApi.createQuestion(selectedCaseId, {
        case_id: selectedCaseId,
        transfer_pack_id: selectedPackId || undefined,
        question_text: questionText.trim(),
        why_it_matters: whyItMatters.trim() || undefined,
        priority,
      });
      setShowModal(false);
      setQuestionText('');
      setWhyItMatters('');
      setSelectedPackId('');
      loadQuestions();
    } catch (err) {
      alert('Failed to submit question: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsSubmittingQuestion(false);
    }
  }

  async function handleAnswerSubmit(questionId) {
    if (!responseText.trim()) return;

    setIsSubmittingAnswer(true);
    try {
      await questionApi.submitResponse(questionId, {
        response_text: responseText.trim(),
      });
      setAnsweringId(null);
      setResponseText('');
      loadQuestions();
    } catch (err) {
      alert('Failed to submit answer: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsSubmittingAnswer(false);
    }
  }

  async function handleReviewResponse(questionId, action, notes) {
    try {
      await questionApi.reviewResponse(questionId, { action, notes });
      loadQuestions();
    } catch (err) {
      alert('Failed to review answer: ' + (err.response?.data?.detail || err.message));
    }
  }

  async function handleTransitionQuestion(questionId, newStatus) {
    try {
      await questionApi.updateQuestion(questionId, { status: newStatus });
      loadQuestions();
    } catch (err) {
      alert('Failed to update question status: ' + (err.response?.data?.detail || err.message));
    }
  }

  return (
    <div className={styles.container}>
      {/* Page Header */}
      <div className={styles.header}>
        <div>
          <h1 style={{ margin: 0, fontSize: 'var(--text-2xl)', fontWeight: 'var(--weight-bold)' }}>
            Targeted Questions
          </h1>
          <p className={styles.subtitle}>
            Direct knowledge transfer inquiries to resolve architectural ambiguities, runbook gaps, and operational edge-cases.
          </p>
        </div>
        <button className={styles.askBtn} onClick={() => setShowModal(true)}>
          <Plus size={16} />
          Ask Question
        </button>
      </div>

      {/* Filter Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.filterRow}>
          {['ALL', 'OPEN', 'ANSWERED', 'RESOLVED', 'DISMISSED'].map((status) => (
            <button
              key={status}
              className={`${styles.filterChip} ${filterStatus === status ? styles.activeChip : ''}`}
              onClick={() => setFilterStatus(status)}
            >
              {status === 'ALL' ? 'All Questions' : status.charAt(0) + status.slice(1).toLowerCase()}
            </button>
          ))}
        </div>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
          {questions.length} question{questions.length === 1 ? '' : 's'}
        </span>
      </div>

      {/* Questions List */}
      {loading ? (
        <div className={styles.emptyState}>Loading questions...</div>
      ) : questions.length === 0 ? (
        <div className={styles.emptyState}>
          <HelpCircle size={40} style={{ opacity: 0.3, marginBottom: 'var(--space-sm)' }} />
          <p>No questions found for the selected filter.</p>
        </div>
      ) : (
        <div className={styles.list}>
          {questions.map((q) => {
            const isAnswering = answeringId === q.id;
            const statusUpper = (q.status || '').toUpperCase();

            return (
              <div key={q.id} className={styles.questionCard}>
                {/* Card Header & Badges */}
                <div className={styles.cardHeader}>
                  <div className={styles.badges}>
                    {q.case_title && (
                      <span className={styles.caseTag}>
                        Case #{q.case_number || 1}: {q.case_title}
                      </span>
                    )}
                    {q.transfer_pack_name && (
                      <span className={styles.caseTag} style={{ backgroundColor: 'var(--color-bg-tertiary)', color: 'var(--color-accent)' }}>
                        <FolderKanban size={11} style={{ display: 'inline', marginRight: 3, verticalAlign: 'middle' }} />
                        {q.transfer_pack_name}
                      </span>
                    )}
                    <span
                      className={`${styles.badge} ${
                        statusUpper === 'OPEN'
                          ? styles.badgeOpen
                          : statusUpper === 'ANSWERED'
                          ? styles.badgeAnswered
                          : styles.badgeResolved
                      }`}
                    >
                      {q.status}
                    </span>
                    <span
                      className={`${styles.badgePriority} ${
                        q.priority === 'CRITICAL'
                          ? styles.priorityCritical
                          : q.priority === 'HIGH'
                          ? styles.priorityHigh
                          : styles.priorityMedium
                      }`}
                    >
                      {q.priority}
                    </span>
                  </div>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
                    {new Date(q.created_at).toLocaleDateString()}
                  </span>
                </div>

                {/* Question Title & Why it Matters */}
                <h3 className={styles.questionTitle}>{q.question_text}</h3>

                {q.why_it_matters && (
                  <div className={styles.whyCallout}>
                    <strong>Why this matters:</strong> {q.why_it_matters}
                  </div>
                )}

                {/* Metadata */}
                <div className={styles.metaRow}>
                  {q.created_by_name && (
                    <div className={styles.metaItem}>
                      <User size={13} /> Asked by {q.created_by_name}
                    </div>
                  )}
                  {q.assigned_to_name && (
                    <div className={styles.metaItem}>
                      <HelpCircle size={13} /> Assigned to <strong>{q.assigned_to_name}</strong>
                    </div>
                  )}
                </div>

                {/* Responses Thread */}
                {q.responses && q.responses.length > 0 && (
                  <div className={styles.responsesSection}>
                    {q.responses.map((resp) => {
                      const reviewUpper = (resp.review_state || '').toUpperCase();
                      return (
                        <div key={resp.id} className={styles.responseCard}>
                          <div className={styles.responseHeader}>
                            <span>
                              Answer by <strong>{resp.respondent_name || 'Respondent'}</strong>
                            </span>
                            <span
                              className={`${styles.responseReviewBadge} ${
                                reviewUpper === 'ACCEPTED'
                                  ? styles.reviewAccepted
                                  : reviewUpper === 'REJECTED'
                                  ? styles.reviewRejected
                                  : styles.reviewPending
                              }`}
                            >
                              {resp.review_state}
                            </span>
                          </div>
                          <div className={styles.responseText}>{resp.response_text}</div>
                          {resp.review_notes && (
                            <div style={{ marginTop: '4px', fontSize: '11px', color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                              Review note: {resp.review_notes}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Inline Answer Box */}
                {isAnswering && (
                  <div className={styles.inlineAnswerBox}>
                    <textarea
                      rows={3}
                      className={styles.answerInput}
                      placeholder="Write your answer, providing architectural rationale or pointing to relevant codebase files..."
                      value={responseText}
                      onChange={(e) => setResponseText(e.target.value)}
                    />
                    <div style={{ display: 'flex', gap: 'var(--space-xs)', justifyContent: 'flex-end' }}>
                      <button
                        className={styles.cancelBtn}
                        onClick={() => {
                          setAnsweringId(null);
                          setResponseText('');
                        }}
                      >
                        Cancel
                      </button>
                      <button
                        className={styles.submitBtn}
                        disabled={isSubmittingAnswer}
                        onClick={() => handleAnswerSubmit(q.id)}
                      >
                        {isSubmittingAnswer ? 'Submitting...' : 'Submit Answer'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Actions Row */}
                <div className={styles.actionRow}>
                  {!isAnswering && statusUpper !== 'RESOLVED' && statusUpper !== 'DISMISSED' && (
                    <button className={styles.answerBtn} onClick={() => setAnsweringId(q.id)}>
                      <MessageSquare size={13} />
                      {q.responses?.length > 0 ? 'Add Follow-up Answer' : 'Answer Question'}
                    </button>
                  )}

                  {/* If answered, allow reviewer to accept / request revision / amend */}
                  {statusUpper === 'ANSWERED' && q.responses?.length > 0 && (
                    <>
                      <button
                        className={styles.acceptBtn}
                        onClick={() => handleReviewResponse(q.id, 'accept')}
                      >
                        <CheckCircle2 size={13} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} />
                        Accept Answer
                      </button>
                      <button
                        className={styles.rejectBtn}
                        onClick={() => handleReviewResponse(q.id, 'reject')}
                      >
                        <XCircle size={13} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} />
                        Request Revision
                      </button>
                    </>
                  )}

                  {/* Reopen if resolved or dismissed */}
                  {(statusUpper === 'RESOLVED' || statusUpper === 'DISMISSED') && (
                    <button
                      className={styles.answerBtn}
                      onClick={() => handleTransitionQuestion(q.id, 'OPEN')}
                    >
                      <RotateCcw size={13} /> Reopen Question
                    </button>
                  )}

                  {/* Dismiss if open */}
                  {statusUpper === 'OPEN' && (
                    <button
                      style={{
                        background: 'transparent',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-muted)',
                        padding: 'var(--space-xs) var(--space-md)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: 'var(--text-xs)',
                        cursor: 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                      }}
                      onClick={() => handleTransitionQuestion(q.id, 'DISMISSED')}
                    >
                      <Ban size={12} /> Dismiss
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Ask Question Modal */}
      {showModal && (
        <div className={styles.modalBackdrop} onClick={() => setShowModal(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <h2 style={{ margin: 0, fontSize: 'var(--text-lg)', fontWeight: 'var(--weight-semibold)' }}>
              Ask a Handover Question
            </h2>
            <form onSubmit={handleCreateQuestion} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
              {cases.length > 0 && (
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Handover Case</label>
                  <select
                    className={styles.formSelect}
                    value={selectedCaseId}
                    onChange={(e) => setSelectedCaseId(e.target.value)}
                  >
                    {cases.map((c) => (
                      <option key={c.id} value={c.id}>
                        Case #{c.case_number || 1}: {c.title}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {availablePacks.length > 0 && (
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Related Transfer Pack (Optional)</label>
                  <select
                    className={styles.formSelect}
                    value={selectedPackId}
                    onChange={(e) => setSelectedPackId(e.target.value)}
                  >
                    <option value="">General (Case-wide knowledge gap)</option>
                    {availablePacks.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Question</label>
                <textarea
                  required
                  rows={3}
                  className={styles.formTextarea}
                  placeholder="e.g. What happens if the background worker connection drops during high-throughput ingestion?"
                  value={questionText}
                  onChange={(e) => setQuestionText(e.target.value)}
                />
              </div>

              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Why It Matters (Operational Context)</label>
                <textarea
                  rows={2}
                  className={styles.formTextarea}
                  placeholder="Explain why this context is essential for zero-downtime continuity..."
                  value={whyItMatters}
                  onChange={(e) => setWhyItMatters(e.target.value)}
                />
              </div>

              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Priority</label>
                <select
                  className={styles.formSelect}
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                >
                  <option value="CRITICAL">Critical (Immediate Operational Risk)</option>
                  <option value="HIGH">High (Key Architecture Decision)</option>
                  <option value="MEDIUM">Medium (General Knowledge Transfer)</option>
                  <option value="LOW">Low (Minor Documentation Detail)</option>
                </select>
              </div>

              <div className={styles.modalActions}>
                <button type="button" className={styles.cancelBtn} onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className={styles.submitBtn} disabled={isSubmittingQuestion}>
                  {isSubmittingQuestion ? 'Creating...' : 'Submit Question'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
