import { useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  FolderKanban,
  GitBranch,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  FileStack,
  Layers,
} from 'lucide-react';
import { transferPackApi } from '../../api/transferPack.api';
import { evidenceApi } from '../../api/evidence.api';
import { ClaimCard } from '../../components/claim-card/claim-card';
import styles from './transfer-pack-detail.module.css';

const CLAIM_TYPES = [
  { id: 'ALL', label: 'All Claims' },
  { id: 'WORK_ITEM', label: 'Work Items' },
  { id: 'DECISION', label: 'Decisions' },
  { id: 'DEPENDENCY', label: 'Dependencies' },
  { id: 'RISK', label: 'Risks' },
  { id: 'OPERATIONAL_NOTE', label: 'Operational Notes' },
  { id: 'KNOWLEDGE_GAP', label: 'Knowledge Gaps' },
  { id: 'NEXT_ACTION', label: 'Next Actions' },
];

export default function TransferPackDetailPage() {
  const { caseId, packId } = useParams();
  const [selectedType, setSelectedType] = useState('ALL');

  // 1. Fetch Transfer Pack details
  const { data: pack, isLoading: packLoading } = useQuery({
    queryKey: ['transfer-pack', packId],
    queryFn: () => transferPackApi.getPack(packId),
    enabled: !!packId,
  });

  // 2. Fetch all claims for this pack
  const { data: claims, isLoading: claimsLoading } = useQuery({
    queryKey: ['pack-claims', packId],
    queryFn: () => evidenceApi.listClaimsForPack(packId),
    enabled: !!packId,
  });

  // Calculate evidence state breakdown
  const stats = useMemo(() => {
    const list = claims || [];
    return {
      total: list.length,
      supported: list.filter((c) => c.evidence_state === 'SUPPORTED').length,
      inferred: list.filter((c) => c.evidence_state === 'INFERRED').length,
      conflicting: list.filter((c) => c.evidence_state === 'CONFLICTING').length,
      unknown: list.filter((c) => c.evidence_state === 'UNKNOWN').length,
    };
  }, [claims]);

  // Filter claims
  const filteredClaims = useMemo(() => {
    if (!claims) return [];
    if (selectedType === 'ALL') return claims;
    return claims.filter((c) => c.claim_type === selectedType);
  }, [claims, selectedType]);

  if (packLoading) {
    return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--color-text-muted)' }}>Loading Transfer Pack…</div>;
  }

  if (!pack) {
    return (
      <div style={{ textAlign: 'center', padding: '3rem' }}>
        <h3>Transfer Pack not found</h3>
        <Link to={`/cases/${caseId}`}>Return to Handover Case</Link>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Back to Case */}
      <Link to={`/cases/${caseId}`} className={styles.backLink}>
        <ArrowLeft size={14} /> Back to Handover Case
      </Link>

      {/* Pack Header Card */}
      <div className={styles.headerCard}>
        <div className={styles.headerTop}>
          <div className={styles.titleArea}>
            <div className={styles.titleRow}>
              <h2>{pack.name}</h2>
              {pack.component_area && (
                <span className={styles.areaBadge}>{pack.component_area}</span>
              )}
              <span className={styles.areaBadge}>{pack.status}</span>
            </div>
            <p className={styles.packDesc}>{pack.description || 'No description provided.'}</p>
          </div>
        </div>

        <div className={styles.packMetaGrid}>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>Historical Owner</span>
            <span className={styles.metaValue}>{pack.recorded_owner_name || 'Unassigned'}</span>
          </div>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>Suggested Successor</span>
            <span className={styles.metaValue}>{pack.suggested_successor_name || 'Pending assignment'}</span>
          </div>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>Created Date</span>
            <span className={styles.metaValue}>{new Date(pack.created_at).toLocaleDateString()}</span>
          </div>
        </div>
      </div>

      {/* Grounded Evidence Breakdown Bar */}
      <div className={styles.breakdownBar}>
        <span className={styles.breakdownTitle}>Evidence Integrity Profile ({stats.total} claims)</span>
        <div className={styles.breakdownPills}>
          <div className={styles.statPill} title="Fully grounded in direct source records">
            <span className={`${styles.statDot} ${styles.dotSupported}`} />
            <span>{stats.supported} Supported</span>
          </div>
          <div className={styles.statPill} title="Derived or inferred from related activity">
            <span className={`${styles.statDot} ${styles.dotInferred}`} />
            <span>{stats.inferred} Inferred</span>
          </div>
          {stats.conflicting > 0 && (
            <div className={styles.statPill} title="Directly conflicting evidence found">
              <span className={`${styles.statDot} ${styles.dotConflicting}`} />
              <span>{stats.conflicting} Conflicting</span>
            </div>
          )}
          {stats.unknown > 0 && (
            <div className={styles.statPill} title="Unverified claims or knowledge gaps">
              <span className={`${styles.statDot} ${styles.dotUnknown}`} />
              <span>{stats.unknown} Unknown</span>
            </div>
          )}
        </div>
      </div>

      {/* Section Filter Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.filterChips}>
          {CLAIM_TYPES.map((t) => (
            <button
              key={t.id}
              className={`${styles.filterChip} ${selectedType === t.id ? styles.filterChipActive : ''}`}
              onClick={() => setSelectedType(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
          Showing {filteredClaims.length} of {stats.total} claims
        </span>
      </div>

      {/* Claims Stream */}
      {claimsLoading ? (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--color-text-muted)' }}>
          Loading grounded claims…
        </div>
      ) : filteredClaims.length === 0 ? (
        <div className={styles.emptyState}>
          <Layers size={32} />
          <h3>No claims found in this category</h3>
          <p>Select "All Claims" or run AI reconstruction to generate additional claims.</p>
        </div>
      ) : (
        <div className={styles.claimsList}>
          {filteredClaims.map((claim) => (
            <ClaimCard key={claim.id} claim={claim} />
          ))}
        </div>
      )}
    </div>
  );
}
