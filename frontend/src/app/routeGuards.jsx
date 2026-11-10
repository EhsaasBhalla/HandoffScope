import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

/**
 * Wraps routes that require authentication.
 * Redirects to /login if not authenticated.
 */
export function ProtectedRoute() {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        color: 'var(--color-text-muted)',
      }}>
        Loading…
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}

/**
 * Wraps routes that require a specific capability.
 * Falls back to a "not authorised" message if the user lacks the capability.
 */
export function RoleRoute({ capability, children }) {
  // Full capability check will be implemented in Phase 2 task 2.7
  // For now, pass through
  return children || <Outlet />;
}
