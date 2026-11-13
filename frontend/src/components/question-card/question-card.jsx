import { useState, useEffect, useRef, memo } from 'react';
import {
  Ban,
  CheckCircle2,
  ExternalLink,
  FileEdit,
  FileText,
  FolderKanban,
  GitPullRequest,
  HelpCircle,
  Link2,
  MessageSquare,
  Paperclip,
  RotateCcw,
  Sparkles,
  Upload,
  User,
  X,
  XCircle,
} from 'lucide-react';
import { usePermissions } from '../../hooks/usePermissions';
import { sourceApi } from '../../api/source.api';
import { evidenceApi } from '../../api/evidence.api';
import { documentApi } from '../../api/document.api';
import styles from './question-card.module.css';

function QuestionThreadCardComponent({
  q,
  onSubmitAnswer,
  onGenerateAiAnswer,
  onReviewResponse,
  onTransitionStatus,
  showCaseTag = false,
}) {
  const { hasCapability } = usePermissions();
  const [isAnswering, setIsAnswering] = useState(false);
  const [answerText, setAnswerText] = useState('');
  const [isSubmittingHuman, setIsSubmittingHuman] = useState(false);

  const [isGeneratingAi, setIsGeneratingAi] = useState(false);
  const [aiError, setAiError] = useState('');

  const [amendingResp, setAmendingResp] = useState(null);
  const [amendedText, setAmendedText] = useState('');
  const [amendNotes, setAmendNotes] = useState('');
  const [isReviewing, setIsReviewing] = useState(false);
  const [isTransitioning, setIsTransitioning] = useState(false);

  const [promotionBanner, setPromotionBanner] = useState(null);
  const [inspectSource, setInspectSource] = useState(null);
  const [inspectLoading, setInspectLoading] = useState(false);
  const [inspectError, setInspectError] = useState('');

  // Resource Attachments State
  const [attachments, setAttachments] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [showRepoPicker, setShowRepoPicker] = useState(false);
  const [repoRecords, setRepoRecords] = useState([]);
  const [repoRecordsLoading, setRepoRecordsLoading] = useState(false);
  const fileInputRef = useRef(null);

  useEffect(() => {
    if (!inspectSource) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setInspectSource(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [inspectSource]);

  if (!q) return null;

  const statusUpper = (q.status || '').toUpperCase();
  const canGenerateAi =
    hasCapability('question.generate_ai') &&
    !['RESOLVED', 'DISMISSED', 'CANCELLED'].includes(statusUpper);
  const canHumanAnswer =
    hasCapability('question.answer') &&
    !['RESOLVED', 'DISMISSED', 'CANCELLED'].includes(statusUpper);
  const canReview = hasCapability('question.review');

  const latestResp =
    Array.isArray(q.responses) && q.responses.length > 0
      ? q.responses[q.responses.length - 1]
      : null;
  const latestPendingReview =
    statusUpper === 'ANSWERED' &&
    latestResp &&
    (latestResp.review_state || '').toUpperCase() === 'PENDING_REVIEW';

  const handleOpenCitation = async (ref) => {
    if (!ref || (!ref.source_id && !ref.document_id)) return;
    setInspectError('');
    setInspectSource({ loading: true, ref });
    setInspectLoading(true);
    try {
      if (ref.source_type === 'DOCUMENT' || ref.document_id) {
        const docId = ref.document_id || ref.source_id;
        setInspectSource({
          type: 'DOCUMENT',
          title: ref.title || 'Attached Document',
          body: ref.excerpt || 'Document file attachment',
          meta: `Document Attachment #${docId}`,
          url: `/api/v1/documents/${docId}/view`,
          locator: ref.locator,
        });
      } else if (ref.source_type === 'CLAIM') {
        const claim = await evidenceApi.getClaim(ref.source_id);
        setInspectSource({
          type: 'CLAIM',
          title: claim?.title || 'Claim Citation',
          body: claim?.body_text || '',
          meta: `Claim (${claim?.claim_type || 'Unknown'}) • ${claim?.review_state || 'n/a'} • ${claim?.evidence_state || 'n/a'}`,
          locator: ref.locator,
          url: ref.source_url || (claim?.id ? `/api/v1/claims/${claim.id}` : null),
        });
      } else {
        const rec = await sourceApi.getCaseSourceRecord(q.case_id, ref.source_id);
        setInspectSource({
          type: rec?.record_type || 'RECORD',
          title: rec?.title || 'Source Record',
          body: rec?.body || '',
          meta: `${rec?.record_type || 'Record'} #${rec?.external_id || 'n/a'} • Author: ${rec?.author_name || 'unknown'} • State: ${rec?.state || 'n/a'}`,
          url: rec?.url || ref.source_url,
          locator: ref.locator,
        });
      }
    } catch (err) {
      setInspectError(err?.data?.detail || err?.message || 'Unable to load source details.');
      setInspectSource(null);
    } finally {
      setInspectLoading(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!q.case_id) {
      setAiError('Cannot attach file: question is not associated with a case.');
      return;
    }
    setIsUploading(true);
    setAiError('');
    try {
      const doc = await documentApi.uploadDocument(q.case_id, file);
      const newAtt = {
        title: file.name,
        type: 'DOCUMENT',
        document_id: doc.id,
        url: `/api/v1/documents/${doc.id}/view`,
        size_bytes: file.size,
      };
      setAttachments((prev) => [...prev, newAtt]);
    } catch (err) {
      setAiError(err?.data?.detail || err?.message || 'Failed to upload attachment.');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleOpenRepoPicker = async () => {
    if (!q.case_id) {
      setAiError('Cannot attach repo resources: question has no associated case.');
      return;
    }
    setShowRepoPicker(true);
    setRepoRecordsLoading(true);
    try {
      const res = await sourceApi.listCaseSourceRecords(q.case_id, { limit: 50 });
      setRepoRecords(Array.isArray(res) ? res : res?.items || []);
    } catch (err) {
      setAiError(err?.data?.detail || err?.message || 'Failed to load repository records.');
    } finally {
      setRepoRecordsLoading(false);
    }
  };

  const handleSelectRepoRecord = (rec) => {
    const cleanId = rec.id ? String(rec.id).replace('sr-', '') : '';
    const newAtt = {
      title: rec.title || `${rec.record_type} #${rec.external_id || cleanId.slice(0, 7)}`,
      type: rec.record_type || 'COMMIT',
      source_id: cleanId,
      url: rec.url || '',
    };
    if (!attachments.some((a) => a.title === newAtt.title && a.url === newAtt.url)) {
      setAttachments((prev) => [...prev, newAtt]);
    }
    setShowRepoPicker(false);
  };

  const handleRemoveAttachment = (idxToRemove) => {
    setAttachments((prev) => prev.filter((_, idx) => idx !== idxToRemove));
  };

  const handleGenerateClick = async () => {
    if (isGeneratingAi || !onGenerateAiAnswer) return;
    setAiError('');
    setIsGeneratingAi(true);
    try {
      await onGenerateAiAnswer(q.id);
    } catch (err) {
      setAiError(err?.data?.detail || err?.data?.error?.message || err?.message || 'Failed to generate AI draft.');
    } finally {
      setIsGeneratingAi(false);
    }
  };

  const handleHumanSubmit = async () => {
    if (!answerText.trim() || isSubmittingHuman || !onSubmitAnswer) return;
    setAiError('');
    setIsSubmittingHuman(true);
    try {
      await onSubmitAnswer(q.id, answerText.trim(), {
        attachments: attachments.length > 0 ? attachments : undefined,
      });
      setIsAnswering(false);
      setAnswerText('');
      setAttachments([]);
    } catch (err) {
      setAiError(err?.data?.detail || err?.data?.error?.message || err?.message || 'Failed to submit answer.');
    } finally {
      setIsSubmittingHuman(false);
    }
  };

  const handleReviewAction = async (action, extra = {}) => {
    if (isReviewing || !onReviewResponse) return;
    setAiError('');
    setIsReviewing(true);
    try {
      const updated = await onReviewResponse(q.id, { action, ...extra });
      if (updated?.promotion_result) {
        setPromotionBanner(updated.promotion_result);
      }
      if (action === 'amend') {
        setAmendingResp(null);
        setAmendedText('');
        setAmendNotes('');
      }
    } catch (err) {
      setAiError(err?.data?.detail || err?.data?.error?.message || err?.message || 'Failed to review response.');
    } finally {
      setIsReviewing(false);
    }
  };

  const handleTransition = async (newStatus) => {
    if (!onTransitionStatus || isTransitioning) return;
    setAiError('');
    setIsTransitioning(true);
    try {
      await onTransitionStatus(q.id, newStatus);
    } catch (err) {
      setAiError(err?.data?.detail || err?.message || 'Failed to update question status.');
    } finally {
      setIsTransitioning(false);
    }
  };

  const formattedDate = q.created_at
    ? (() => {
        try {
          const d = new Date(q.created_at);
          return isNaN(d.getTime()) ? q.created_at : d.toLocaleDateString();
        } catch {
          return q.created_at;
        }
      })()
    : '';

  const statusBadgeClass =
    statusUpper === 'RESOLVED'
      ? styles.statusResolved
      : statusUpper === 'ANSWERED'
      ? styles.statusAnswered
      : styles.statusOpen;

  const priorityBadgeClass =
    q.priority === 'CRITICAL'
      ? styles.priorityCritical
      : q.priority === 'HIGH'
      ? styles.priorityHigh
      : '';

  return (
    <div className={styles.card}>
      {/* Top Badge Bar */}
      <div className={styles.topBar}>
        <div className={styles.badgeGroup}>
          {showCaseTag && q.case_title && (
            <span className={styles.caseBadge}>
              Case #{q.case_number || 1}: {q.case_title}
            </span>
          )}
          {q.transfer_pack_name && (
            <span className={styles.packBadge}>
              <FolderKanban size={11} />
              {q.transfer_pack_name}
            </span>
          )}
          <span className={`${styles.statusBadge} ${statusBadgeClass}`}>{q.status}</span>
          <span className={`${styles.priorityBadge} ${priorityBadgeClass}`}>{q.priority}</span>
        </div>
        {formattedDate && <span className={styles.dateMeta}>{formattedDate}</span>}
      </div>

      {/* Question Heading */}
      <h4 className={styles.heading}>{q.question_text}</h4>

      {q.why_it_matters && (
        <div className={styles.whyBox}>
          <strong>Why this matters:</strong> {q.why_it_matters}
        </div>
      )}

      {q.claim_title && (
        <div className={styles.linkedClaim}>
          Linked Claim: <strong>{q.claim_title}</strong>
        </div>
      )}

      <div className={styles.actorsRow}>
        {q.created_by_name && (
          <span className={styles.actorItem}>
            <User size={12} /> Asked by {q.created_by_name}
          </span>
        )}
        {q.assigned_to_name && (
          <span className={styles.actorItem}>
            <HelpCircle size={12} /> Assigned to <strong>{q.assigned_to_name}</strong>
          </span>
        )}
      </div>

      {promotionBanner && (
        <div className={styles.promotionBanner}>
          <span>{promotionBanner.message}</span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setPromotionBanner(null);
            }}
            className={styles.dismissBannerBtn}
            aria-label="Dismiss notice"
          >
            <X size={13} />
          </button>
        </div>
      )}

      {/* Responses Thread */}
      {q.responses && q.responses.length > 0 && (
        <div className={styles.responsesList}>
          {q.responses.map((resp) => {
            const revUpper = (resp.review_state || '').toUpperCase();
            const isAi = !!resp.is_ai_generated;
            const isInsufficient = resp.answer_status === 'insufficient';
            const isConflicting = resp.answer_status === 'conflicting';
            const isFallback =
              resp.provenance?.fallback_used ||
              resp.ai_provider === 'mock' ||
              resp.ai_provider === 'mock_fallback';

            const reviewClass =
              revUpper === 'ACCEPTED' || revUpper === 'AMENDED'
                ? styles.reviewAccepted
                : revUpper === 'REJECTED'
                ? styles.reviewRejected
                : styles.reviewPending;

            return (
              <div
                key={resp.id}
                className={`${styles.responseCard} ${isAi ? styles.responseCardAi : ''}`}
              >
                <div className={styles.responseHeader}>
                  <div className={styles.responseBadges}>
                    {isAi ? (
                      <span className={styles.aiDraftBadge}>
                        <Sparkles size={11} />
                        {revUpper === 'PENDING_REVIEW'
                          ? 'Suggested draft — awaiting review'
                          : `Draft (${revUpper})`}
                      </span>
                    ) : (
                      <span className={styles.humanBadge}>
                        Human-Confirmed • {resp.respondent_name || 'Engineer'}
                      </span>
                    )}

                    {isAi && isFallback && (
                      <span className={styles.fallbackTag}>
                        [{resp.ai_provider}: {resp.ai_model}]
                      </span>
                    )}
                    {isInsufficient && (
                      <span className={styles.insufficientBadge}>Insufficient Evidence</span>
                    )}
                    {isConflicting && (
                      <span className={styles.conflictBadge}>Conflicting Sources</span>
                    )}
                  </div>

                  <span className={`${styles.reviewStateTag} ${reviewClass}`}>
                    {resp.review_state}
                  </span>
                </div>

                <div className={styles.responseBody}>{resp.response_text}</div>

                {resp.limitations && (
                  <div className={styles.limitationsBox}>
                    <strong>Limitations / Staleness:</strong> {resp.limitations}
                  </div>
                )}

                {Array.isArray(resp.conflicts) && resp.conflicts.length > 0 && (
                  <div className={styles.conflictsBox}>
                    <strong>Source Conflicts:</strong>
                    <ul className={styles.conflictsList}>
                      {resp.conflicts.map((c, idx) => (
                        <li key={idx}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {Array.isArray(resp.evidence_references) && resp.evidence_references.length > 0 && (
                  <div className={styles.citationsRow}>
                    {resp.evidence_references.map((ref, idx) => {
                      const directUrl =
                        ref.url ||
                        ref.source_url ||
                        (ref.document_id ? `/api/v1/documents/${ref.document_id}/view` : null);
                      return (
                        <div key={idx} style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleOpenCitation(ref);
                            }}
                            className={`${styles.citationBtn} ${ref.is_stale ? styles.citationBtnStale : ''}`}
                            title={ref.excerpt || 'Inspect source evidence'}
                          >
                            <FileText size={11} />
                            <span>{ref.title || ref.locator || (ref.source_id ? String(ref.source_id).slice(0, 8) : 'Source')}</span>
                            {ref.is_stale && <span className={styles.staleTag}>(Potentially Stale)</span>}
                          </button>
                          {directUrl && (
                            <a
                              href={directUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className={styles.citationNewTabLink}
                              title="Open source in new tab"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <ExternalLink size={11} />
                            </a>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* User/AI Attached Resources */}
                {Array.isArray(resp.attachments) && resp.attachments.length > 0 && (
                  <div className={styles.attachmentsSection}>
                    <div className={styles.attachmentsHeader}>
                      <Paperclip size={12} />
                      <span>Attached Resources ({resp.attachments.length})</span>
                    </div>
                    <div className={styles.attachmentsList}>
                      {resp.attachments.map((att, idx) => {
                        const openUrl =
                          att.url ||
                          (att.document_id ? `/api/v1/documents/${att.document_id}/view` : null);
                        return (
                          <span key={idx} className={styles.attachmentPill}>
                            <span className={styles.attachmentTitle}>{att.title || 'Attachment'}</span>
                            {openUrl && (
                              <a
                                href={openUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className={styles.openAttachmentLink}
                                title="Open resource in new tab"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <span>Open</span>
                                <ExternalLink size={10} />
                              </a>
                            )}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}

                {resp.review_notes && (
                  <div className={styles.reviewNotes}>Review note: {resp.review_notes}</div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {inspectError && <div className={styles.inspectError}>{inspectError}</div>}
      {aiError && <div className={styles.actionError}>{aiError}</div>}

      {/* Inline Human Answer Box */}
      {isAnswering && (
        <div className={styles.inlineEditor} onClick={(e) => e.stopPropagation()}>
          <textarea
            rows={3}
            placeholder="Write a human-confirmed answer citing relevant runbooks, PRs, or operational steps..."
            value={answerText}
            onChange={(e) => setAnswerText(e.target.value)}
            className={styles.textareaInput}
            disabled={isSubmittingHuman}
          />

          {/* Attached items preview */}
          {attachments.length > 0 && (
            <div className={styles.attachmentsSection}>
              <div className={styles.attachmentsHeader}>
                <Paperclip size={12} />
                <span>Attached Resources ({attachments.length})</span>
              </div>
              <div className={styles.attachmentsList}>
                {attachments.map((att, idx) => (
                  <span key={idx} className={styles.attachmentPill}>
                    <span className={styles.attachmentTitle}>{att.title}</span>
                    {att.url && (
                      <a
                        href={att.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.openAttachmentLink}
                        title="Open in new tab"
                      >
                        <ExternalLink size={10} />
                      </a>
                    )}
                    <button
                      type="button"
                      onClick={() => handleRemoveAttachment(idx)}
                      className={styles.removeAttachmentBtn}
                      title="Remove attachment"
                    >
                      <X size={12} />
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Attach toolbar */}
          <div className={styles.attachToolbar}>
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileUpload}
              style={{ display: 'none' }}
              disabled={isUploading || isSubmittingHuman}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading || isSubmittingHuman}
              className={styles.attachBtn}
              title="Upload and attach local document or file"
            >
              <Upload size={12} />
              <span>{isUploading ? 'Uploading…' : 'Attach Document'}</span>
            </button>
            <button
              type="button"
              onClick={handleOpenRepoPicker}
              disabled={isUploading || isSubmittingHuman}
              className={styles.attachBtn}
              title="Select commit, PR, or file from connected GitHub repo"
            >
              <GitPullRequest size={12} />
              <span>Attach from Repo</span>
            </button>
          </div>

          <div className={styles.editorActions}>
            <button
              type="button"
              disabled={isSubmittingHuman}
              onClick={() => {
                setIsAnswering(false);
                setAnswerText('');
                setAttachments([]);
              }}
              className={`${styles.btnBase} ${styles.btnGhost}`}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={isSubmittingHuman || !answerText.trim()}
              onClick={handleHumanSubmit}
              className={`${styles.btnBase} ${styles.btnPrimary}`}
            >
              {isSubmittingHuman ? 'Submitting...' : 'Submit Human Answer'}
            </button>
          </div>
        </div>
      )}

      {/* Inline Edit & Accept (Amend) Box */}
      {amendingResp && (
        <div className={styles.amendEditor} onClick={(e) => e.stopPropagation()}>
          <label className={styles.editorLabel}>Edit &amp; Accept Answer</label>
          <textarea
            rows={4}
            value={amendedText}
            onChange={(e) => setAmendedText(e.target.value)}
            className={styles.textareaInput}
            disabled={isReviewing}
          />
          <input
            type="text"
            placeholder="Review note (optional)"
            value={amendNotes}
            onChange={(e) => setAmendNotes(e.target.value)}
            className={styles.textInput}
            disabled={isReviewing}
          />
          <div className={styles.editorActions}>
            <button
              type="button"
              disabled={isReviewing}
              onClick={() => setAmendingResp(null)}
              className={`${styles.btnBase} ${styles.btnGhost}`}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={isReviewing || !amendedText.trim()}
              onClick={() =>
                handleReviewAction('amend', {
                  amended_text: amendedText.trim(),
                  notes: amendNotes.trim() || undefined,
                })
              }
              className={`${styles.btnBase} ${styles.btnSuccess}`}
            >
              {isReviewing ? 'Saving...' : 'Save Amended Answer & Accept'}
            </button>
          </div>
        </div>
      )}

      {/* Actions Row */}
      <div className={styles.actionsRow} onClick={(e) => e.stopPropagation()}>
        {canGenerateAi && (
          <button
            type="button"
            disabled={isGeneratingAi}
            onClick={handleGenerateClick}
            className={`${styles.btnBase} ${styles.btnAiDraft}`}
          >
            <Sparkles size={13} />
            {isGeneratingAi
              ? 'Generating Grounded Draft…'
              : aiError
              ? 'Retry Draft'
              : 'Generate Evidence Draft'}
          </button>
        )}

        {!isAnswering && canHumanAnswer && (
          <button
            type="button"
            onClick={() => setIsAnswering(true)}
            className={`${styles.btnBase} ${styles.btnSecondary}`}
          >
            <MessageSquare size={12} />
            {q.responses?.length > 0 ? 'Add Human Answer' : 'Answer Question'}
          </button>
        )}

        {canReview && latestPendingReview && !amendingResp && (
          <>
            <button
              type="button"
              disabled={isReviewing}
              onClick={() => handleReviewAction('accept')}
              className={`${styles.btnBase} ${styles.btnSuccess}`}
            >
              <CheckCircle2 size={12} /> Accept Answer
            </button>
            <button
              type="button"
              disabled={isReviewing}
              onClick={() => {
                setAmendingResp(latestResp);
                setAmendedText(latestResp.response_text || '');
              }}
              className={`${styles.btnBase} ${styles.btnSecondary}`}
            >
              <FileEdit size={12} /> Edit &amp; Accept
            </button>
            <button
              type="button"
              disabled={isReviewing}
              onClick={() => handleReviewAction('reject', { notes: 'Needs further verification.' })}
              className={`${styles.btnBase} ${styles.btnDanger}`}
            >
              <XCircle size={12} /> Reject / Request Revision
            </button>
          </>
        )}

        {canReview && statusUpper === 'DRAFT' && (
          <button
            type="button"
            disabled={isTransitioning}
            onClick={() => handleTransition('OPEN')}
            className={`${styles.btnBase} ${styles.btnPrimary}`}
          >
            <CheckCircle2 size={12} /> {isTransitioning ? 'Publishing…' : 'Publish Question'}
          </button>
        )}

        {canReview && (statusUpper === 'RESOLVED' || statusUpper === 'DISMISSED') && (
          <button
            type="button"
            disabled={isTransitioning}
            onClick={() => handleTransition('OPEN')}
            className={`${styles.btnBase} ${styles.btnGhost}`}
          >
            <RotateCcw size={12} /> {isTransitioning ? 'Reopening…' : 'Reopen Question'}
          </button>
        )}

        {canReview && statusUpper === 'OPEN' && (
          <button
            type="button"
            disabled={isTransitioning}
            onClick={() => handleTransition('DISMISSED')}
            className={`${styles.btnBase} ${styles.btnGhostMuted}`}
          >
            <Ban size={12} /> {isTransitioning ? 'Dismissing…' : 'Dismiss'}
          </button>
        )}
      </div>

      {/* Citation Drilldown Modal */}
      {inspectSource && (
        <div
          className={styles.modalBackdrop}
          onClick={() => setInspectSource(null)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="inspect-source-title"
        >
          <div
            className={styles.modalDialog}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.modalHeader}>
              <h3 id="inspect-source-title" className={styles.modalTitle}>
                {inspectLoading ? 'Loading Source Details…' : inspectSource.title || 'Source Record'}
              </h3>
              <button
                type="button"
                onClick={() => setInspectSource(null)}
                className={styles.modalCloseBtn}
                aria-label="Close source details"
              >
                <X size={18} />
              </button>
            </div>
            {!inspectLoading && (
              <>
                <div className={styles.modalMeta}>
                  {inspectSource.meta}
                  {inspectSource.locator ? ` • Locator: ${inspectSource.locator}` : ''}
                </div>
                <pre className={styles.modalBody}>
                  {inspectSource.body || 'No body content.'}
                </pre>
                {inspectSource.url && (
                  <a
                    href={inspectSource.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.externalRefLink}
                  >
                    Open Resource in New Tab <ExternalLink size={12} />
                  </a>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* Repo Resource Picker Modal */}
      {showRepoPicker && (
        <div
          className={styles.repoPickerModal}
          onClick={() => setShowRepoPicker(false)}
          role="dialog"
          aria-modal="true"
        >
          <div
            className={styles.repoPickerContent}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.modalHeader}>
              <h3 className={styles.modalTitle}>Attach Repository Resource</h3>
              <button
                type="button"
                onClick={() => setShowRepoPicker(false)}
                className={styles.modalCloseBtn}
              >
                <X size={18} />
              </button>
            </div>
            {repoRecordsLoading ? (
              <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Loading repository records…</p>
            ) : repoRecords.length === 0 ? (
              <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                No repository records or commits found for this case.
              </p>
            ) : (
              <div className={styles.repoPickerList}>
                {repoRecords.map((rec) => (
                  <div
                    key={rec.id}
                    className={styles.repoPickerItem}
                    onClick={() => handleSelectRepoRecord(rec)}
                  >
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>
                        {rec.title || `${rec.record_type} #${rec.external_id || ''}`}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                        {rec.record_type} • {rec.author_name || 'unknown'} • {rec.external_id || ''}
                      </div>
                    </div>
                    <span style={{ fontSize: 11, color: 'var(--color-accent-text)', fontWeight: 500 }}>
                      Attach
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export const QuestionThreadCard = memo(QuestionThreadCardComponent);
export default QuestionThreadCard;
