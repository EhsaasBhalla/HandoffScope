/**
 * Permission check hook.
 *
 * Implements client-side capability checking aligned with the backend 9x30 RBAC matrix.
 */
import { useAuth } from '../context/AuthContext';

// Capability mapping for demo users aligned with their actual roles
const USER_CAPABILITY_MAP = {
  // Maya Sharma (Workspace OWNER / Project LEAD)
  'maya.sharma@example.test': [
    'workspace.manage', 'workspace.view', 'workspace.members.manage',
    'project.create', 'project.manage', 'project.view', 'project.members.manage',
    'case.create', 'case.manage', 'case.view', 'source.connect', 'source.view',
    'source.import', 'extraction.trigger', 'extraction.view', 'pack.create',
    'pack.manage', 'pack.view', 'review.request', 'review.submit', 'review.view',
    'question.create', 'question.view', 'question.answer',
    'share.manage', 'successor.view', 'acceptance.manage',
    'document.upload', 'document.view', 'audit.view', 'settings.manage', 'timeline.view',
  ],
  // Arjun Patel (Workspace ADMIN / Departing Contributor)
  'arjun.patel@example.test': [
    'workspace.view', 'project.view', 'case.view', 'source.view',
    'extraction.view', 'pack.view', 'question.view', 'question.answer', 'timeline.view',
  ],
  // Kabir Singh (Technical Reviewer)
  'kabir.singh@example.test': [
    'workspace.view', 'project.view', 'case.view', 'source.view',
    'extraction.view', 'pack.view', 'pack.manage', 'review.submit', 'review.view',
    'question.create', 'question.view', 'question.answer', 'timeline.view',
    'document.view', 'audit.view',
  ],
  // Aisha Khan (Designated Successor / Recipient)
  'aisha.khan@example.test': [
    'workspace.view', 'project.view', 'case.view', 'source.view',
    'extraction.view', 'pack.view', 'successor.view', 'acceptance.manage',
    'question.create', 'question.view', 'timeline.view', 'document.view',
  ],
  // Neha Gupta / Dev Mehta / Priya Nair (Contributors)
  'neha.gupta@example.test': [
    'workspace.view', 'project.view', 'case.view', 'source.view',
    'pack.view', 'question.view', 'question.answer', 'timeline.view',
  ],
  'default_contributor': [
    'workspace.view', 'project.view', 'case.view', 'source.view',
    'question.view', 'timeline.view',
  ],
};

export function usePermissions() {
  const { user } = useAuth();

  function hasCapability(capability) {
    if (!capability) return true;
    if (!user) return false;

    // Prefer authoritative server-computed RBAC capabilities from /auth/me & /auth/login
    if (Array.isArray(user.capabilities) && user.capabilities.length > 0) {
      return user.capabilities.includes(capability);
    }

    // Legacy fallback for minimal mock test user objects
    const userCaps = USER_CAPABILITY_MAP[user.email] || USER_CAPABILITY_MAP['default_contributor'];
    return userCaps.includes(capability);
  }

  function hasAnyCapability(...capabilities) {
    return capabilities.some(hasCapability);
  }

  return { hasCapability, hasAnyCapability };
}
