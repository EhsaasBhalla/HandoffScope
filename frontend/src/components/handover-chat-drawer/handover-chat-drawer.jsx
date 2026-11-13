import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BookOpen,
  ExternalLink,
  FileText,
  Lock,
  MessageSquare,
  Plus,
  Send,
  ShieldCheck,
  X,
  Loader2,
} from 'lucide-react';
import { ragApi } from '../../api/rag.api';
import styles from './handover-chat-drawer.module.css';

const SAMPLE_QUESTIONS = [
  'What are the critical unresolved risks or knowledge gaps?',
  'Which services or transfer packs am I taking over?',
  'What next actions should be verified before production deployment?',
  'Are there conflicting architectural decisions across project records?',
];

export function HandoverChatDrawer({
  isOpen,
  onClose,
  caseId,
  hasApprovedVersion = false,
  approvedVersionNumber = null,
  isRecipientOnly = false,
}) {
  const queryClient = useQueryClient();
  const [selectedThreadId, setSelectedThreadId] = useState('');
  const [questionInput, setQuestionInput] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [restrictedNotice, setRestrictedNotice] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState(null);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (onClose) onClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose]);

  const { data: threads } = useQuery({
    queryKey: ['rag-threads', caseId],
    queryFn: () => (caseId ? ragApi.listThreads(caseId) : []),
    enabled: isOpen && !!caseId,
  });

  const { data: threadDetail, isLoading: threadLoading } = useQuery({
    queryKey: ['rag-thread-detail', caseId, selectedThreadId],
    queryFn: () => (caseId && selectedThreadId ? ragApi.getThread(caseId, selectedThreadId) : null),
    enabled: isOpen && !!caseId && !!selectedThreadId,
  });

  const askMutation = useMutation({
    mutationFn: (payload) => ragApi.askQuestion(caseId, payload),
    onSuccess: (res) => {
      setErrorMsg('');
      setQuestionInput('');
      if (res?.thread?.id) {
        setSelectedThreadId(res.thread.id);
        queryClient.invalidateQueries({ queryKey: ['rag-threads', caseId] });
        queryClient.invalidateQueries({ queryKey: ['rag-thread-detail', caseId, res.thread.id] });
      }
      setRestrictedNotice(Boolean(res?.restricted_evidence_excluded));
    },
    onError: (err) => {
      setErrorMsg(err.data?.detail || err.message || 'Unable to answer question right now.');
    },
  });

  if (!isOpen) return null;

  const isDisabledForRecipient = isRecipientOnly && !hasApprovedVersion;
  const activeModeLabel =
    threadDetail?.context_mode === 'DRAFT_CONTEXT' || (!hasApprovedVersion && !isRecipientOnly)
      ? 'Draft Context'
      : `Approved Snapshot v${threadDetail?.pinned_version_number || approvedVersionNumber || 1}`;
  const isApprovedBadge = activeModeLabel.startsWith('Approved');

  const handleSubmit = (qText) => {
    const trimmed = (qText ?? questionInput).trim();
    if (!trimmed || askMutation.isPending || isDisabledForRecipient || !caseId) return;
    setErrorMsg('');
    askMutation.mutate({
      question: trimmed,
      thread_id: selectedThreadId || undefined,
      context_mode: hasApprovedVersion ? 'APPROVED_SNAPSHOT' : isRecipientOnly ? 'APPROVED_SNAPSHOT' : 'DRAFT_CONTEXT',
    });
  };

  const messageList = Array.isArray(threadDetail?.messages) ? threadDetail.messages : [];

  return (
    <div
      className={styles.backdrop}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="handover-chat-title"
    >
      <div className={styles.drawer} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.headerTitleWrap}>
            <div className={styles.titleRow}>
              <BookOpen size={18} style={{ color: 'var(--color-accent-text)' }} />
              <h3 id="handover-chat-title" className={styles.title}>Ask the Handover</h3>
            </div>
            <span className={`${styles.contextBadge} ${isApprovedBadge ? styles.badgeApproved : styles.badgeDraft}`}>
              <ShieldCheck size={11} />
              {activeModeLabel}
            </span>
          </div>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Close assistant">
            <X size={18} />
          </button>
        </div>

        <div className={styles.toolbar}>
          <select
            className={styles.threadSelect}
            value={selectedThreadId}
            onChange={(e) => {
              setSelectedThreadId(e.target.value);
              setSelectedCitation(null);
            }}
            aria-label="Select conversation thread"
          >
            <option value="">New conversation thread…</option>
            {(threads || []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.pinned_version_number ? `[v${t.pinned_version_number}] ` : '[Draft] '}
                {t.title} ({t.message_count ?? 0})
              </option>
            ))}
          </select>
          <button
            type="button"
            className={styles.newThreadBtn}
            onClick={() => {
              setSelectedThreadId('');
              setSelectedCitation(null);
              setRestrictedNotice(false);
              setErrorMsg('');
            }}
          >
            <Plus size={13} /> New Thread
          </button>
        </div>

        <div className={styles.messagesPane}>
          {isDisabledForRecipient ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyTitle}>Assistant Locked Until Snapshot Approval</div>
              <p className={styles.emptyHint}>
                Successor questions are restricted to approved, immutable version snapshots. Once a reviewer approves v1, you can query it here.
              </p>
            </div>
          ) : selectedThreadId && threadLoading ? (
            <div className={styles.emptyHint}>Loading conversation history…</div>
          ) : !messageList.length ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyTitle}>
                <MessageSquare size={14} style={{ display: 'inline', marginRight: 6, verticalAlign: 'middle' }} />
                Evidence-Grounded Handover Q&amp;A
              </div>
              <p className={styles.emptyHint}>
                Answers cite only approved claims, evidence excerpts, and permitted source records pinned to this handover context.
              </p>
              <div className={styles.starterList}>
                {SAMPLE_QUESTIONS.map((sample) => (
                  <button
                    key={sample}
                    type="button"
                    className={styles.starterBtn}
                    disabled={askMutation.isPending}
                    onClick={() => handleSubmit(sample)}
                  >
                    {sample}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messageList.map((m) => {
              const isUser = m.role === 'user';
              const gClass =
                m.grounding_status === 'ANSWERED'
                  ? styles.groundAnswered
                  : m.grounding_status === 'CONFLICTING_EVIDENCE'
                  ? styles.groundConflict
                  : styles.groundInsufficient;

              return (
                <div
                  key={m.id}
                  className={`${styles.msgBubble} ${isUser ? styles.msgUser : styles.msgAssistant}`}
                >
                  <div className={styles.msgHeader}>
                    <strong>{isUser ? 'You' : 'Handover Assistant'}</strong>
                    {!isUser && m.grounding_status && (
                      <span className={`${styles.groundingPill} ${gClass}`}>
                        {m.grounding_status}
                      </span>
                    )}
                  </div>
                  <div className={styles.msgBody}>{m.content_text}</div>

                  {!isUser && m.limitations && (
                    <div className={styles.limitationsNote}>{m.limitations}</div>
                  )}

                  {!isUser && Array.isArray(m.citations) && m.citations.length > 0 && (
                    <div className={styles.citationsWrap}>
                      {m.citations.map((cit, citIdx) => (
                        <button
                          key={cit.chunk_id || citIdx}
                          type="button"
                          className={styles.citationPill}
                          onClick={() =>
                            setSelectedCitation(
                              selectedCitation?.chunk_id === cit.chunk_id ? null : cit
                            )
                          }
                        >
                          <FileText size={11} />
                          <span>{cit.locator || cit.title}</span>
                        </button>
                      ))}
                    </div>
                  )}

                  {!isUser && m.retrieval_mode && (
                    <div style={{ fontSize: '10px', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
                      Mode: {m.retrieval_mode} • Model: {m.model_used || 'n/a'}
                    </div>
                  )}
                </div>
              );
            })
          )}

          {selectedCitation && (
            <div className={styles.citationPreviewBox}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <strong>{selectedCitation.title}</strong>
                <button type="button" onClick={() => setSelectedCitation(null)}>
                  <X size={12} />
                </button>
              </div>
              <div>{selectedCitation.excerpt}</div>
              {selectedCitation.url && (
                <a
                  href={selectedCitation.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginTop: 4 }}
                >
                  Open Source Reference <ExternalLink size={11} />
                </a>
              )}
            </div>
          )}
        </div>

        {restrictedNotice && (
          <div className={styles.restrictedNotice}>
            <Lock size={13} />
            <span>
              Notice: Restricted evidence requiring elevated clearance was excluded prior to retrieval.
            </span>
          </div>
        )}

        {errorMsg && <div className={styles.errorBox}>{errorMsg}</div>}

        <form
          className={styles.composer}
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
        >
          <input
            type="text"
            className={styles.input}
            placeholder={
              isDisabledForRecipient
                ? 'Requires approved version snapshot...'
                : 'Ask about architecture, risks, or procedures...'
            }
            disabled={isDisabledForRecipient || askMutation.isPending}
            value={questionInput}
            onChange={(e) => setQuestionInput(e.target.value)}
          />
          <button
            type="submit"
            className={styles.sendBtn}
            disabled={isDisabledForRecipient || askMutation.isPending || !questionInput.trim()}
          >
            {askMutation.isPending ? (
              <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
            ) : (
              <Send size={14} />
            )}
            {askMutation.isPending ? 'Thinking…' : 'Ask'}
          </button>
        </form>
      </div>
    </div>
  );
}
