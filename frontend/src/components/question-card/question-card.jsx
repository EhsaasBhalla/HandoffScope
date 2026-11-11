import { useState } from 'react';
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ExternalLink,
  FileText,
  FolderKanban,
  HelpCircle,
  MessageSquare,
  RotateCcw,
  Sparkles,
  User,
  X,
  XCircle,
  FileEdit,
} from 'lucide-react';
import { usePermissions } from '../../hooks/usePermissions';
import { sourceApi } from '../../api/source.api';
import { evidenceApi } from '../../api/evidence.api';

export function QuestionThreadCard({
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

  const [promotionBanner, setPromotionBanner] = useState(null);
  const [inspectSource, setInspectSource] = useState(null);
  const [inspectLoading, setInspectLoading] = useState(false);
  const [inspectError, setInspectError] = useState('');

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
    setInspectError('');
    setInspectSource({ loading: true, ref });
    setInspectLoading(true);
    try {
      if (ref.source_type === 'CLAIM') {
        const claim = await evidenceApi.getClaim(ref.source_id);
        setInspectSource({
          type: 'CLAIM',
          title: claim.title,
          body: claim.body_text,
          meta: `Claim (${claim.claim_type}) • ${claim.review_state} • ${claim.evidence_state}`,
          locator: ref.locator,
        });
      } else {
        const rec = await sourceApi.getCaseSourceRecord(q.case_id, ref.source_id);
        setInspectSource({
          type: rec.record_type,
          title: rec.title,
          body: rec.body,
          meta: `${rec.record_type} #${rec.external_id} • Author: ${rec.author_name || 'unknown'} • State: ${rec.state || 'n/a'}`,
          url: rec.url,
          locator: ref.locator,
        });
      }
    } catch (err) {
      setInspectError(err.data?.detail || err.message || 'Unable to load source details.');
      setInspectSource(null);
    } finally {
      setInspectLoading(false);
    }
  };

  const handleGenerateClick = async () => {
    if (isGeneratingAi) return;
    setAiError('');
    setIsGeneratingAi(true);
    try {
      await onGenerateAiAnswer(q.id);
    } catch (err) {
      setAiError(err.data?.detail || err.data?.error?.message || err.message || 'Failed to generate AI draft.');
    } finally {
      setIsGeneratingAi(false);
    }
  };

  const handleHumanSubmit = async () => {
    if (!answerText.trim() || isSubmittingHuman) return;
    setAiError('');
    setIsSubmittingHuman(true);
    try {
      await onSubmitAnswer(q.id, answerText.trim());
      setIsAnswering(false);
      setAnswerText('');
    } catch (err) {
      setAiError(err.data?.detail || err.data?.error?.message || err.message || 'Failed to submit answer.');
    } finally {
      setIsSubmittingHuman(false);
    }
  };

  const handleReviewAction = async (action, extra = {}) => {
    if (isReviewing) return;
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
      setAiError(err.data?.detail || err.data?.error?.message || err.message || 'Failed to review response.');
    } finally {
      setIsReviewing(false);
    }
  };

  return (
    <div
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-md)',
        padding: '16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
      }}
    >
      {/* Top Badge Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
          {showCaseTag && q.case_title && (
            <span style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '999px', backgroundColor: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}>
              Case #{q.case_number || 1}: {q.case_title}
            </span>
          )}
          {q.transfer_pack_name && (
            <span style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '999px', backgroundColor: 'rgba(99, 102, 241, 0.14)', color: 'var(--color-accent-text)' }}>
              <FolderKanban size={11} style={{ display: 'inline', marginRight: 3, verticalAlign: 'middle' }} />
              {q.transfer_pack_name}
            </span>
          )}
          <span
            style={{
              fontSize: '11px',
              fontWeight: 600,
              padding: '2px 8px',
              borderRadius: '999px',
              backgroundColor:
                statusUpper === 'RESOLVED'
                  ? 'rgba(16, 185, 129, 0.14)'
                  : statusUpper === 'ANSWERED'
                  ? 'rgba(245, 158, 11, 0.16)'
                  : 'rgba(59, 130, 246, 0.14)',
              color:
                statusUpper === 'RESOLVED'
                  ? '#34d399'
                  : statusUpper === 'ANSWERED'
                  ? '#fbbf24'
                  : '#60a5fa',
            }}
          >
            {q.status}
          </span>
          <span
            style={{
              fontSize: '11px',
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: '999px',
              backgroundColor:
                q.priority === 'CRITICAL'
                  ? 'rgba(239, 68, 68, 0.16)'
                  : q.priority === 'HIGH'
                  ? 'rgba(245, 158, 11, 0.16)'
                  : 'var(--color-bg-tertiary)',
              color: q.priority === 'CRITICAL' ? '#f87171' : q.priority === 'HIGH' ? '#fbbf24' : 'var(--color-text-secondary)',
            }}
          >
            {q.priority}
          </span>
        </div>
        <span style={{ fontSize: '11px', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
          {new Date(q.created_at).toLocaleDateString()}
        </span>
      </div>

      {/* Question Heading */}
      <h4 style={{ margin: 0, fontSize: '15px', fontWeight: 600, color: 'var(--color-text-primary)' }}>
        {q.question_text}
      </h4>

      {q.why_it_matters && (
        <div
          style={{
            backgroundColor: 'var(--color-bg-primary)',
            padding: '8px 12px',
            borderRadius: '6px',
            borderLeft: '3px solid var(--color-accent)',
            fontSize: '12px',
            color: 'var(--color-text-secondary)',
          }}
        >
          <strong>Why this matters:</strong> {q.why_it_matters}
        </div>
      )}

      {q.claim_title && (
        <div style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
          Linked Claim: <strong>{q.claim_title}</strong>
        </div>
      )}

      <div style={{ display: 'flex', gap: '12px', fontSize: '12px', color: 'var(--color-text-muted)', flexWrap: 'wrap' }}>
        {q.created_by_name && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <User size={12} /> Asked by {q.created_by_name}
          </span>
        )}
        {q.assigned_to_name && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <HelpCircle size={12} /> Assigned to <strong>{q.assigned_to_name}</strong>
          </span>
        )}
      </div>

      {promotionBanner && (
        <div
          style={{
            padding: '8px 12px',
            borderRadius: '6px',
            backgroundColor: 'rgba(16, 185, 129, 0.12)',
            border: '1px solid rgba(16, 185, 129, 0.35)',
            fontSize: '12px',
            color: '#34d399',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>{promotionBanner.message}</span>
          <button
            onClick={() => setPromotionBanner(null)}
            style={{ background: 'transparent', border: 'none', color: '#34d399', cursor: 'pointer' }}
          >
            <X size={13} />
          </button>
        </div>
      )}

      {/* Responses Thread */}
      {q.responses && q.responses.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '4px' }}>
          {q.responses.map((resp) => {
            const revUpper = (resp.review_state || '').toUpperCase();
            const isAi = !!resp.is_ai_generated;
            const isInsufficient = resp.answer_status === 'insufficient';
            const isConflicting = resp.answer_status === 'conflicting';
            const isFallback = resp.provenance?.fallback_used || resp.ai_provider === 'mock' || resp.ai_provider === 'mock_fallback';

            return (
              <div
                key={resp.id}
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  border: `1px solid ${isAi ? 'rgba(99, 102, 241, 0.35)' : 'var(--color-border)'}`,
                  borderRadius: '6px',
                  padding: '12px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                    {isAi ? (
                      <span
                        style={{
                          fontSize: '11px',
                          fontWeight: 700,
                          padding: '2px 8px',
                          borderRadius: '999px',
                          backgroundColor: 'rgba(99, 102, 241, 0.16)',
                          color: '#a5b4fc',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                        }}
                      >
                        <Sparkles size={11} />
                        {revUpper === 'PENDING_REVIEW'
                          ? 'AI-suggested draft — awaiting review'
                          : `AI Draft (${revUpper})`}
                      </span>
                    ) : (
                      <span
                        style={{
                          fontSize: '11px',
                          fontWeight: 700,
                          padding: '2px 8px',
                          borderRadius: '999px',
                          backgroundColor: 'rgba(16, 185, 129, 0.12)',
                          color: '#6ee7b7',
                        }}
                      >
                        Human-Confirmed • {resp.respondent_name || 'Engineer'}
                      </span>
                    )}

                    {isAi && isFallback && (
                      <span style={{ fontSize: '10px', color: '#fbbf24', fontFamily: 'var(--font-mono)' }}>
                        [{resp.ai_provider}: {resp.ai_model}]
                      </span>
                    )}
                    {isInsufficient && (
                      <span style={{ fontSize: '11px', padding: '2px 6px', borderRadius: '4px', backgroundColor: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24' }}>
                        Insufficient Evidence
                      </span>
                    )}
                    {isConflicting && (
                      <span style={{ fontSize: '11px', padding: '2px 6px', borderRadius: '4px', backgroundColor: 'rgba(239, 68, 68, 0.15)', color: '#f87171' }}>
                        Conflicting Sources
                      </span>
                    )}
                  </div>

                  <span
                    style={{
                      fontSize: '11px',
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 600,
                      color:
                        revUpper === 'ACCEPTED' || revUpper === 'AMENDED'
                          ? '#34d399'
                          : revUpper === 'REJECTED'
                          ? '#f87171'
                          : '#fbbf24',
                    }}
                  >
                    {resp.review_state}
                  </span>
                </div>

                <div style={{ fontSize: '13px', lineHeight: 1.55, whiteSpace: 'pre-wrap', color: 'var(--color-text-primary)' }}>
                  {resp.response_text}
                </div>

                {resp.limitations && (
                  <div style={{ fontSize: '11px', color: '#fbbf24', backgroundColor: 'rgba(245, 158, 11, 0.08)', padding: '6px 8px', borderRadius: '4px' }}>
                    <strong>Limitations / Staleness:</strong> {resp.limitations}
                  </div>
                )}

                {Array.isArray(resp.conflicts) && resp.conflicts.length > 0 && (
                  <div style={{ fontSize: '11px', color: '#fca5a5', backgroundColor: 'rgba(239, 68, 68, 0.08)', padding: '6px 8px', borderRadius: '4px' }}>
                    <strong>Source Conflicts:</strong>
                    <ul style={{ margin: '4px 0 0', paddingLeft: '16px' }}>
                      {resp.conflicts.map((c, idx) => (
                        <li key={idx}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {Array.isArray(resp.evidence_references) && resp.evidence_references.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', paddingTop: '2px' }}>
                    {resp.evidence_references.map((ref, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => handleOpenCitation(ref)}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '5px',
                          fontSize: '11px',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          backgroundColor: 'var(--color-bg-secondary)',
                          border: `1px solid ${ref.is_stale ? 'rgba(245, 158, 11, 0.45)' : 'var(--color-border)'}`,
                          color: 'var(--color-accent-text)',
                          cursor: 'pointer',
                        }}
                        title={ref.excerpt || 'Inspect source evidence'}
                      >
                        <FileText size={11} />
                        <span>{ref.title || ref.locator || ref.source_id.slice(0, 8)}</span>
                        {ref.is_stale && <span style={{ color: '#fbbf24' }}>(Potentially Stale)</span>}
                      </button>
                    ))}
                  </div>
                )}

                {resp.review_notes && (
                  <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                    Review note: {resp.review_notes}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {inspectError && (
        <div style={{ fontSize: '11px', color: '#f87171' }}>{inspectError}</div>
      )}
      {aiError && (
        <div style={{ fontSize: '12px', color: '#f87171', backgroundColor: 'rgba(239, 68, 68, 0.08)', padding: '6px 10px', borderRadius: '4px' }}>
          {aiError}
        </div>
      )}

      {/* Inline Human Answer Box */}
      {isAnswering && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '4px' }}>
          <textarea
            rows={3}
            placeholder="Write a human-confirmed answer citing relevant runbooks, PRs, or operational steps..."
            value={answerText}
            onChange={(e) => setAnswerText(e.target.value)}
            style={{
              padding: '8px',
              backgroundColor: 'var(--color-bg-primary)',
              border: '1px solid var(--color-border)',
              borderRadius: '6px',
              color: 'var(--color-text-primary)',
              fontSize: '13px',
            }}
          />
          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <button
              onClick={() => {
                setIsAnswering(false);
                setAnswerText('');
              }}
              style={{ padding: '6px 12px', borderRadius: '6px', border: '1px solid var(--color-border)', background: 'transparent', color: 'var(--color-text-secondary)', cursor: 'pointer', fontSize: '12px' }}
            >
              Cancel
            </button>
            <button
              disabled={isSubmittingHuman || !answerText.trim()}
              onClick={handleHumanSubmit}
              style={{ padding: '6px 12px', borderRadius: '6px', border: 'none', backgroundColor: 'var(--color-accent)', color: '#fff', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
            >
              {isSubmittingHuman ? 'Submitting...' : 'Submit Human Answer'}
            </button>
          </div>
        </div>
      )}

      {/* Inline Edit & Accept (Amend) Box */}
      {amendingResp && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '10px', borderRadius: '6px', backgroundColor: 'var(--color-bg-primary)', border: '1px solid var(--color-accent)' }}>
          <label style={{ fontSize: '12px', fontWeight: 600 }}>Edit &amp; Accept Answer</label>
          <textarea
            rows={4}
            value={amendedText}
            onChange={(e) => setAmendedText(e.target.value)}
            style={{ padding: '8px', backgroundColor: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', borderRadius: '6px', color: 'var(--color-text-primary)', fontSize: '13px' }}
          />
          <input
            type="text"
            placeholder="Review note (optional)"
            value={amendNotes}
            onChange={(e) => setAmendNotes(e.target.value)}
            style={{ padding: '6px 8px', backgroundColor: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', borderRadius: '6px', color: 'var(--color-text-primary)', fontSize: '12px' }}
          />
          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <button
              onClick={() => setAmendingResp(null)}
              style={{ padding: '5px 10px', borderRadius: '6px', border: '1px solid var(--color-border)', background: 'transparent', color: 'var(--color-text-secondary)', fontSize: '12px', cursor: 'pointer' }}
            >
              Cancel
            </button>
            <button
              disabled={isReviewing || !amendedText.trim()}
              onClick={() =>
                handleReviewAction('amend', {
                  amended_text: amendedText.trim(),
                  notes: amendNotes.trim() || undefined,
                })
              }
              style={{ padding: '5px 12px', borderRadius: '6px', border: 'none', backgroundColor: '#10b981', color: '#fff', fontSize: '12px', fontWeight: 600, cursor: 'pointer' }}
            >
              {isReviewing ? 'Saving...' : 'Save Amended Answer & Accept'}
            </button>
          </div>
        </div>
      )}

      {/* Actions Row */}
      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', paddingTop: '4px' }}>
        {canGenerateAi && (
          <button
            type="button"
            disabled={isGeneratingAi}
            onClick={handleGenerateClick}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '5px',
              padding: '6px 12px',
              borderRadius: '6px',
              border: '1px solid rgba(99, 102, 241, 0.4)',
              backgroundColor: 'rgba(99, 102, 241, 0.14)',
              color: '#a5b4fc',
              fontSize: '12px',
              fontWeight: 600,
              cursor: isGeneratingAi ? 'wait' : 'pointer',
            }}
          >
            <Sparkles size={13} />
            {isGeneratingAi
              ? 'Generating Grounded Draft…'
              : aiError
              ? 'Retry AI Draft'
              : 'Generate AI Draft'}
          </button>
        )}

        {!isAnswering && canHumanAnswer && (
          <button
            type="button"
            onClick={() => setIsAnswering(true)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '5px',
              padding: '6px 12px',
              borderRadius: '6px',
              border: '1px solid var(--color-border)',
              backgroundColor: 'var(--color-bg-primary)',
              color: 'var(--color-text-primary)',
              fontSize: '12px',
              cursor: 'pointer',
            }}
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
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '6px 12px',
                borderRadius: '6px',
                border: 'none',
                backgroundColor: '#10b981',
                color: '#fff',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
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
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '6px 12px',
                borderRadius: '6px',
                border: '1px solid var(--color-border)',
                backgroundColor: 'var(--color-bg-primary)',
                color: 'var(--color-text-primary)',
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              <FileEdit size={12} /> Edit &amp; Accept
            </button>
            <button
              type="button"
              disabled={isReviewing}
              onClick={() => handleReviewAction('reject', { notes: 'Needs further verification.' })}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '6px 12px',
                borderRadius: '6px',
                border: '1px solid rgba(239, 68, 68, 0.35)',
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                color: '#f87171',
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              <XCircle size={12} /> Reject / Request Revision
            </button>
          </>
        )}

        {canReview && statusUpper === 'DRAFT' && (
          <button
            type="button"
            onClick={() => onTransitionStatus(q.id, 'OPEN')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '6px 12px',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: 'var(--color-accent)',
              color: '#fff',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <CheckCircle2 size={12} /> Publish Question
          </button>
        )}

        {canReview && (statusUpper === 'RESOLVED' || statusUpper === 'DISMISSED') && (
          <button
            type="button"
            onClick={() => onTransitionStatus(q.id, 'OPEN')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '6px 12px',
              borderRadius: '6px',
              border: '1px solid var(--color-border)',
              backgroundColor: 'transparent',
              color: 'var(--color-text-secondary)',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            <RotateCcw size={12} /> Reopen Question
          </button>
        )}

        {canReview && statusUpper === 'OPEN' && (
          <button
            type="button"
            onClick={() => onTransitionStatus(q.id, 'DISMISSED')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '6px 12px',
              borderRadius: '6px',
              border: '1px solid var(--color-border)',
              backgroundColor: 'transparent',
              color: 'var(--color-text-muted)',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            <Ban size={12} /> Dismiss
          </button>
        )}
      </div>

      {/* Citation Drilldown Modal */}
      {inspectSource && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1100,
            padding: '16px',
          }}
          onClick={() => setInspectSource(null)}
        >
          <div
            style={{
              backgroundColor: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              borderRadius: '10px',
              padding: '20px',
              maxWidth: '640px',
              width: '100%',
              maxHeight: '80vh',
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, fontSize: '16px' }}>
                {inspectLoading ? 'Loading Source Details…' : inspectSource.title || 'Source Record'}
              </h3>
              <button
                onClick={() => setInspectSource(null)}
                style={{ background: 'transparent', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer' }}
              >
                <X size={18} />
              </button>
            </div>
            {!inspectLoading && (
              <>
                <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
                  {inspectSource.meta}
                  {inspectSource.locator ? ` • Locator: ${inspectSource.locator}` : ''}
                </div>
                <pre
                  style={{
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'var(--font-sans)',
                    fontSize: '13px',
                    backgroundColor: 'var(--color-bg-primary)',
                    padding: '12px',
                    borderRadius: '6px',
                    border: '1px solid var(--color-border)',
                    margin: 0,
                  }}
                >
                  {inspectSource.body || 'No body content.'}
                </pre>
                {inspectSource.url && (
                  <a
                    href={inspectSource.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ fontSize: '12px', color: 'var(--color-accent-text)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                  >
                    Open Original External Reference <ExternalLink size={12} />
                  </a>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
