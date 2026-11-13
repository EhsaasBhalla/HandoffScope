import { memo } from 'react';
import styles from './freshness-badge.module.css';

function FreshnessBadgeComponent({ freshness }) {
  const norm = (freshness || 'UNKNOWN_FRESHNESS').toUpperCase();

  let dotClass = styles.unknown;
  let label = 'Unknown';

  if (norm === 'CURRENT') {
    dotClass = styles.current;
    label = 'Current';
  } else if (norm === 'POTENTIALLY_STALE') {
    dotClass = styles.stale;
    label = 'Potentially Stale';
  } else if (norm === 'CHANGED_SINCE_APPROVAL') {
    dotClass = styles.changed;
    label = 'Changed Since Approval';
  }

  return (
    <span className={styles.badge}>
      <span className={`${styles.dot} ${dotClass}`} />
      <span>{label}</span>
    </span>
  );
}

export const FreshnessBadge = memo(FreshnessBadgeComponent);
export default FreshnessBadge;
