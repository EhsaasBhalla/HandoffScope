import {
  GitCommit,
  GitPullRequest,
  AlertCircle,
  FileText,
  ExternalLink,
  Lock,
  User,
  Clock,
} from 'lucide-react';
import styles from './evidence-card.module.css';

export function EvidenceCard({ evidence }) {
  if (!evidence) return null;

  const type = (evidence.source_type || 'COMMIT').toUpperCase();

  const renderIcon = () => {
    switch (type) {
      case 'COMMIT':
        return <GitCommit size={14} color="#3b82f6" />;
      case 'PR':
      case 'PULL_REQUEST':
        return <GitPullRequest size={14} color="#8b5cf6" />;
      case 'ISSUE':
        return <AlertCircle size={14} color="#10b981" />;
      case 'DOCUMENT':
        return <FileText size={14} color="var(--color-warning)" />;
      default:
        return <GitCommit size={14} />;
    }
  };

  const formatDate = (isoStr) => {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return d.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
    } catch {
      return isoStr;
    }
  };

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <div className={styles.sourceTypeMeta}>
          {renderIcon()}
          <span className={styles.typePill}>{type}</span>
          {evidence.locator && <span>• {evidence.locator}</span>}
        </div>

        {evidence.is_restricted && (
          <span className={styles.restrictedPill}>
            <Lock size={10} />
            Restricted Document
          </span>
        )}
      </div>

      <div className={styles.titleRow}>
        <h5 className={styles.title}>{evidence.source_title || 'Source Evidence Reference'}</h5>
        {evidence.source_url && (
          <a
            href={evidence.source_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className={styles.externalLink}
            title="Open in GitHub / Source"
          >
            <ExternalLink size={12} />
          </a>
        )}
      </div>

      {evidence.excerpt && (
        <div className={styles.excerpt}>
          "{evidence.excerpt}"
        </div>
      )}

      <div className={styles.footer}>
        <div className={styles.authorMeta}>
          <User size={11} />
          <span>{evidence.source_author || 'Author'}</span>
        </div>
        {evidence.source_timestamp && (
          <div className={styles.authorMeta}>
            <Clock size={11} />
            <span>{formatDate(evidence.source_timestamp)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default EvidenceCard;
