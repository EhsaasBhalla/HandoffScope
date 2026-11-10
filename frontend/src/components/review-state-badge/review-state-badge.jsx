import { Clock, CheckCircle2, Edit3, XCircle, HelpCircle } from 'lucide-react';
import styles from './review-state-badge.module.css';

export function ReviewStateBadge({ state }) {
  const norm = (state || 'PENDING_REVIEW').toUpperCase();

  let className = styles.pending;
  let icon = <Clock size={11} />;
  let label = 'Pending Review';

  if (norm === 'ACCEPTED') {
    className = styles.accepted;
    icon = <CheckCircle2 size={11} />;
    label = 'Accepted';
  } else if (norm === 'EDITED_AND_ACCEPTED') {
    className = styles.accepted;
    icon = <Edit3 size={11} />;
    label = 'Edited & Accepted';
  } else if (norm === 'REJECTED') {
    className = styles.rejected;
    icon = <XCircle size={11} />;
    label = 'Rejected';
  } else if (norm === 'NEEDS_CLARIFICATION') {
    className = styles.clarification;
    icon = <HelpCircle size={11} />;
    label = 'Needs Clarification';
  }

  return (
    <span className={`${styles.badge} ${className}`}>
      {icon}
      <span>{label}</span>
    </span>
  );
}

export default ReviewStateBadge;
