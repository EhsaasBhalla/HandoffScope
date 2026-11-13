import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  HelpCircle,
  Plus,
  Search,
  X,
} from 'lucide-react';
import { questionApi } from '../../api/question.api';
import { transferPackApi } from '../../api/transferPack.api';
import { httpClient } from '../../api/httpClient';
import { useAuth } from '../../context/AuthContext';
import { QuestionThreadCard } from '../../components/question-card/question-card';
import styles from './questions.module.css';

export default function QuestionsPage() {
  const { user } = useAuth();
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');

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

  const loadQuestions = useCallback(async () => {
    setLoading(true);
    try {
      const params = filterStatus !== 'ALL' ? { status: filterStatus } : {};
      const res = await questionApi.listQuestions(params);
      setQuestions(Array.isArray(res) ? res : Array.isArray(res?.data) ? res.data : []);
    } catch (err) {
      console.error('Failed to load questions:', err);
      setQuestions([]);
    } finally {
      setLoading(false);
    }
  }, [filterStatus]);

  const loadCases = useCallback(async () => {
    try {
      const wsRes = await httpClient.get('/api/v1/workspaces');
      if (Array.isArray(wsRes) && wsRes.length > 0) {
        const wsId = wsRes[0].id;
        const pRes = await httpClient.get(`/api/v1/workspaces/${wsId}/projects`);
        const allCases = [];
        if (Array.isArray(pRes)) {
          const casePromises = pRes.map(async (p) => {
            try {
              const cRes = await httpClient.get(`/api/v1/projects/${p.id}/cases`);
              return Array.isArray(cRes) ? cRes : [];
            } catch (_) {
              return [];
            }
          });
          const results = await Promise.all(casePromises);
          allCases.push(...results.flat());
        }
        setCases(allCases);
        setSelectedCaseId((prev) => prev || (allCases[0]?.id || ''));
      }
    } catch (err) {
      console.error('Failed to load cases:', err);
    }
  }, []);

  useEffect(() => {
    loadQuestions();
  }, [loadQuestions, user?.id]);

  useEffect(() => {
    loadCases();
  }, [loadCases]);

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
      alert('Failed to submit question: ' + (err.data?.detail || err.message));
    } finally {
      setIsSubmittingQuestion(false);
    }
  }

  const handleAnswerSubmit = useCallback(async (questionId, text) => {
    try {
      await questionApi.submitResponse(questionId, { response_text: text });
      loadQuestions();
    } catch (err) {
      alert('Failed to submit answer: ' + (err.data?.detail || err.message));
      throw err;
    }
  }, [loadQuestions]);

  const handleGenerateAiAnswer = useCallback(async (questionId) => {
    const updated = await questionApi.generateAiAnswer(questionId);
    loadQuestions();
    return updated;
  }, [loadQuestions]);

  const handleReviewResponse = useCallback(async (questionId, payload) => {
    try {
      const updated = await questionApi.reviewResponse(questionId, payload);
      loadQuestions();
      return updated;
    } catch (err) {
      alert('Failed to review answer: ' + (err.data?.detail || err.data?.error?.message || err.message));
      throw err;
    }
  }, [loadQuestions]);

  const handleTransitionQuestion = useCallback(async (questionId, newStatus) => {
    try {
      await questionApi.updateQuestion(questionId, { status: newStatus });
      loadQuestions();
    } catch (err) {
      alert('Failed to update question status: ' + (err.data?.detail || err.message));
    }
  }, [loadQuestions]);

  const filteredQuestions = useMemo(() => {
    if (!Array.isArray(questions)) return [];
    if (!searchQuery.trim()) return questions;
    const q = searchQuery.toLowerCase();
    return questions.filter((item) => {
      const text = (item.question_text || '').toLowerCase();
      const why = (item.why_it_matters || '').toLowerCase();
      const caseName = (item.case_title || '').toLowerCase();
      return text.includes(q) || why.includes(q) || caseName.includes(q);
    });
  }, [questions, searchQuery]);

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
          {['ALL', 'OPEN', 'DRAFT', 'ANSWERED', 'RESOLVED', 'DISMISSED'].map((status) => (
            <button
              key={status}
              className={`${styles.filterChip} ${filterStatus === status ? styles.activeChip : ''}`}
              onClick={() => setFilterStatus(status)}
            >
              {status === 'ALL' ? 'All Questions' : status.charAt(0) + status.slice(1).toLowerCase()}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', flexWrap: 'wrap' }}>
          <div className={styles.searchWrap}>
            <Search size={14} style={{ color: 'var(--color-text-muted)' }} />
            <input
              type="text"
              placeholder="Search questions or context…"
              className={styles.searchInput}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button
                className={styles.clearBtn}
                onClick={() => setSearchQuery('')}
                title="Clear search"
              >
                <X size={12} />
              </button>
            )}
          </div>

          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
            {filteredQuestions.length} of {questions.length} question{questions.length === 1 ? '' : 's'}
          </span>
        </div>
      </div>

      {/* Questions List */}
      {loading ? (
        <div className={styles.emptyState}>Loading questions...</div>
      ) : filteredQuestions.length === 0 ? (
        <div className={styles.emptyState}>
          <HelpCircle size={40} style={{ opacity: 0.3, marginBottom: 'var(--space-sm)' }} />
          <p>
            {questions.length === 0
              ? 'No questions found for the selected status filter.'
              : 'No questions match your search query.'}
          </p>
          {(filterStatus !== 'ALL' || searchQuery) && (
            <button
              className={styles.resetFiltersBtn}
              onClick={() => {
                setFilterStatus('ALL');
                setSearchQuery('');
              }}
            >
              Reset Filters
            </button>
          )}
        </div>
      ) : (
        <div className={styles.list}>
          {filteredQuestions.map((q) => (
            <QuestionThreadCard
              key={q.id}
              q={q}
              showCaseTag={true}
              onSubmitAnswer={handleAnswerSubmit}
              onGenerateAiAnswer={handleGenerateAiAnswer}
              onReviewResponse={handleReviewResponse}
              onTransitionStatus={handleTransitionQuestion}
            />
          ))}
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
