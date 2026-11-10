/**
 * Permission check hook.
 *
 * Implements client-side capability checking aligned with the backend 9x30 RBAC matrix.
 */
import { useAuth } from '../context/AuthContext';

// Capability mapping for demo users based on their primary roles
const USER_CAPABILITY_MAP = {
  // Maya Sharma (OWNER / LEAD)
  'maya.sharma@example.test': [
    'workspace.manage', 'workspace.view', 'project.manage', 'project.view',
    'case.create', 'case.manage', 'case.view', 'source.connect', 'source.view',
    'source.import', 'extraction.trigger', 'extraction.view', 'pack.create',
    'pack.manage', 'pack.view', 'review.request', 'review.view', 'share.manage',
    'document.upload', 'document.view', 'audit.view', 'settings.manage', 'timeline.view',
  ],
  // Arjun Patel (ADMIN / Departing CONTRIBUTOR)
  'arjun.patel@example.test': [
    'workspace.view', 'project.view', 'case.view', 'source.view',
    'extraction.view', 'pack.view', 'question.answer', 'timeline.view',
  ],
  // Neha Gupta (MEMBER / Successor RECIPIENT)
  'neha.gupta@example.test': [
    'workspace.view', 'project.view', 'case.view', 'pack.view',
    'successor.view', 'question.create', 'question.view', 'acceptance.manage', 'timeline.view',
  ],
  // Aisha Khan (MEMBER / REVIEWER)
  'aisha.khan@example.test': [
    'workspace.view', 'project.view', 'case.view', 'extraction.view',
    'pack.view', 'review.submit', 'review.view', 'question.create', 'question.view', 'timeline.view',
  ],
  // Dev Mehta / Kabir Singh / Priya Nair (Contributors)
  'default_contributor': [
    'workspace.view', 'project.view', 'case.view', 'source.view', 'timeline.view',
  ],
};

export function usePermissions() {
  const { user } = useAuth();

  function hasCapability(capability) {
    if (!capability) return true;
    if (!user) return false;

    // Direct lookup for seeded demo accounts
    const userCaps = USER_CAPABILITY_MAP[user.email] || USER_CAPABILITY_MAP['default_contributor'];
    return userCaps.includes(capability);
  }

  function hasAnyCapability(...capabilities) {
    return capabilities.some(hasCapability);
  }

  return { hasCapability, hasAnyCapability };
}
