import { createBrowserRouter } from 'react-router-dom';
import { ProtectedRoute } from './routeGuards';
import { AppShell } from '../layouts/app-shell/app-shell';
import { AuthLayout } from '../layouts/auth-layout/auth-layout';

// ── Page Imports (lazy-loaded for code splitting) ────────────
import LoginPage from '../pages/login/login';
import OverviewPage from '../pages/overview/overview';
import ProjectsPage from '../pages/projects/projects';
import ProjectDetailPage from '../pages/project-detail/project-detail';
import HandoverCasesPage from '../pages/handover-cases/handover-cases';
import HandoverCaseDetailPage from '../pages/handover-case-detail/handover-case-detail';
import CreateHandoverCasePage from '../pages/create-handover-case/create-handover-case';
import SourcesPage from '../pages/sources/sources';
import TimelinePage from '../pages/timeline/timeline';
import QuestionsPage from '../pages/questions/questions';
import ReviewQueuePage from '../pages/review-queue/review-queue';
import TransferPackDetailPage from '../pages/transfer-pack-detail/transfer-pack-detail';
import PeopleAccessPage from '../pages/people-access/people-access';
import SuccessorViewPage from '../pages/successor-view/successor-view';
import AuditLogPage from '../pages/audit-log/audit-log';
import SettingsPage from '../pages/settings/settings';

export const router = createBrowserRouter([
  // ── Public routes ──────────────────────────────────────────
  {
    element: <AuthLayout />,
    children: [
      { path: '/login', element: <LoginPage /> },
    ],
  },

  // ── Protected routes ───────────────────────────────────────
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: '/', element: <OverviewPage /> },
          { path: '/projects', element: <ProjectsPage /> },
          { path: '/projects/:projectId', element: <ProjectDetailPage /> },
          { path: '/projects/:projectId/cases/new', element: <CreateHandoverCasePage /> },
          { path: '/cases', element: <HandoverCasesPage /> },
          { path: '/cases/:caseId', element: <HandoverCaseDetailPage /> },
          { path: '/cases/:caseId/packs/:packId', element: <TransferPackDetailPage /> },
          { path: '/sources', element: <SourcesPage /> },
          { path: '/timeline', element: <TimelinePage /> },
          { path: '/questions', element: <QuestionsPage /> },
          { path: '/review', element: <ReviewQueuePage /> },
          { path: '/people', element: <PeopleAccessPage /> },
          { path: '/successor', element: <SuccessorViewPage /> },
          { path: '/audit', element: <AuditLogPage /> },
          { path: '/settings', element: <SettingsPage /> },
        ],
      },
    ],
  },
]);
