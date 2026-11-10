import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CheckSquare,
  Lightbulb,
  Link2,
  AlertTriangle,
  BookOpen,
  HelpCircle,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  FileCheck2,
} from 'lucide-react';
import { evidenceApi } from '../../api/evidence.api';
import { EvidenceStateBadge } from '../evidence-state-badge/evidence-state-badge';
import { FreshnessBadge } from '../freshness-badge/freshness-badge';
import { ReviewStateBadge } from '../review-state-badge/review-state-badge';
import { EvidenceCard } from '../evidence-card/evidence-card';
import styles from './claim-card.module.css';

export function ClaimCard({ claim }) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Fetch full evidence items if expanded
  const { data: claimDetail, isLoading: evidenceLoading } = useQuery({
    queryKey: ['claim-detail', claim.id],
    queryFn: () => evidenceApi.getClaim(claim.id),
    enabled: isExpanded,
  });

  const renderTypeIcon = (type) => {
    switch ((type || '').toUpperCase()) {
      case 'WORK_ITEM':
        return <CheckSquare size={16} />;
      case 'DECISION':
        return <Lightbulb size={16} />;
      case 'DEPENDENCY':
        return <Link2 size={16} />;
      case 'RISK':
        return <AlertTriangle size={16} />;
      case 'OPERATIONAL_NOTE':
        return <BookOpen size={16} />;
      case 'KNOWLEDGE_GAP':
        return <HelpCircle size={16} />;
      case 'NEXT_ACTION':
        return <ArrowRight size={16} />;
      default:
        return <FileCheck2 size={16} />;
    }
  };

  const evidenceItems = claimDetail?.evidence || [];
  const evCount = claim.evidence_count ?? evidenceItems.length;

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <div className={styles.typeMeta}>
          <div className={styles.typeIconWrap}>
            {renderTypeIcon(claim.claim_type)}
          </div>
          <span className={styles.typeLabel}>{claim.claim_type?.replace('_', ' ')}</span>
        </div>

        <div className={styles.badgesRow}>
          {claim.priority && claim.priority === 'HIGH' && (
            <span className={styles.priorityBadge}>{claim.priority} Priority</span>
          )}
          <EvidenceStateBadge state={claim.evidence_state} />
          <FreshnessBadge freshness={claim.freshness} />
          <ReviewStateBadge state={claim.review_state} />
        </div>
      </div>

      <h4 className={styles.title}>{claim.title}</h4>

      {claim.body_text && (
        <p className={styles.body}>{claim.body_text}</p>
      )}

      <div className={styles.footer}>
        <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
          {evCount} grounded evidence reference{evCount === 1 ? '' : 's'}
        </span>

        <button
          className={styles.expandBtn}
          onClick={() => setIsExpanded((prev) => !prev)}
        >
          {isExpanded ? (
            <>
              Hide Evidence <ChevronUp size={14} />
            </>
          ) : (
            <>
              Inspect Evidence <ChevronDown size={14} />
            </>
          )}
        </button>
      </div>

      {isExpanded && (
        <div className={styles.evidenceDrawer}>
          <h5 className={styles.drawerTitle}>Grounded Source Citations</h5>
          {evidenceLoading ? (
            <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', padding: '0.5rem 0' }}>
              Loading evidence records...
            </div>
          ) : evidenceItems.length === 0 ? (
            <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
              No explicit source citations attached to this claim.
            </div>
          ) : (
            evidenceItems.map((ev) => <EvidenceCard key={ev.id} evidence={ev} />)
          )}
        </div>
      )}
    </div>
  );
}

export default ClaimCard;
