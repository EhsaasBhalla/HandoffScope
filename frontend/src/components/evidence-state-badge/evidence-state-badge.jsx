import { CheckCircle2, HelpCircle, AlertTriangle, AlertCircle } from 'lucide-react';
import styles from './evidence-state-badge.module.css';

export function EvidenceStateBadge({ state }) {
  const norm = (state || 'UNKNOWN').toUpperCase();

  let className = styles.unknown;
  let icon = <HelpCircle size={11} />;
  let label = 'Unknown';

  if (norm === 'SUPPORTED') {
    className = styles.supported;
    icon = <CheckCircle2 size={11} />;
    label = 'Supported';
  } else if (norm === 'INFERRED') {
    className = styles.inferred;
    icon = <AlertTriangle size={11} />;
    label = 'Inferred';
  } else if (norm === 'CONFLICTING') {
    className = styles.conflicting;
    icon = <AlertCircle size={11} />;
    label = 'Conflicting';
  }

  return (
    <span className={`${styles.badge} ${className}`}>
      {icon}
      {label}
    </span>
  );
}

export default EvidenceStateBadge;
