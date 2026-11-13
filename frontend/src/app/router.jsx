import { lazy, Suspense } from 'react';
import { createBrowserRouter } from 'react-router-dom';
import { ProtectedRoute } from './routeGuards';
import { AppShell } from '../layouts/app-shell/app-shell';
import { AuthLayout } from '../layouts/auth-layout/auth-layout';

// ── Fallback Loader Component ────────────────────────────────
function RouteFallback() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '260px',
        width: '100%',
        color: 'var(--color-text-muted, #64748b)',
        fontSize: '13px',
      }}
    >
      <div
        style={{
          width: '20px',
          height: '20px',
          border: '2px solid var(--color-border, #e2e8f0)',
          borderTopColor: 'var(--color-accent, #2563eb)',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
          marginRight: '8px',
        }}
      />
      <span>Loading view…</span>
    </div>
  );
}

function withSuspense(Component) {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Component />
    </Suspense>
  );
}

// ── Page Imports (lazy-loaded for code splitting) ────────────
const LoginPage = lazy(() => import('../pages/login/login'));
const OverviewPage = lazy(() => import('../pages/overview/overview'));
const ProjectsPage = lazy(() => import('../pages/projects/projects'));
const ProjectDetailPage = lazy(() => import('../pages/project-detail/project-detail'));
const HandoverCasesPage = lazy(() => import('../pages/handover-cases/handover-cases'));
const HandoverCaseDetailPage = lazy(() => import('../pages/handover-case-detail/handover-case-detail'));
const CreateHandoverCasePage = lazy(() => import('../pages/create-handover-case/create-handover-case'));
const SourcesPage = lazy(() => import('../pages/sources/sources'));
const TimelinePage = lazy(() => import('../pages/timeline/timeline'));
const QuestionsPage = lazy(() => import('../pages/questions/questions'));
const ReviewQueuePage = lazy(() => import('../pages/review-queue/review-queue'));
const TransferPackDetailPage = lazy(() => import('../pages/transfer-pack-detail/transfer-pack-detail'));
const PeopleAccessPage = lazy(() => import('../pages/people-access/people-access'));
const SuccessorViewPage = lazy(() => import('../pages/successor-view/successor-view'));
const AuditLogPage = lazy(() => import('../pages/audit-log/audit-log'));
const SettingsPage = lazy(() => import('../pages/settings/settings'));

export const router = createBrowserRouter([
  // ── Public routes ──────────────────────────────────────────
  {
    element: <AuthLayout />,
    children: [
      { path: '/login', element: withSuspense(LoginPage) },
    ],
  },

  // ── Protected routes ───────────────────────────────────────
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: '/', element: withSuspense(OverviewPage) },
          { path: '/projects', element: withSuspense(ProjectsPage) },
          { path: '/projects/:projectId', element: withSuspense(ProjectDetailPage) },
          { path: '/projects/:projectId/cases/new', element: withSuspense(CreateHandoverCasePage) },
          { path: '/cases', element: withSuspense(HandoverCasesPage) },
          { path: '/cases/:caseId', element: withSuspense(HandoverCaseDetailPage) },
          { path: '/cases/:caseId/packs/:packId', element: withSuspense(TransferPackDetailPage) },
          { path: '/sources', element: withSuspense(SourcesPage) },
          { path: '/timeline', element: withSuspense(TimelinePage) },
          { path: '/questions', element: withSuspense(QuestionsPage) },
          { path: '/review', element: withSuspense(ReviewQueuePage) },
          { path: '/people', element: withSuspense(PeopleAccessPage) },
          { path: '/successor', element: withSuspense(SuccessorViewPage) },
          { path: '/audit', element: withSuspense(AuditLogPage) },
          { path: '/settings', element: withSuspense(SettingsPage) },
        ],
      },
    ],
  },
]);
