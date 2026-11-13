import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { usePermissions } from '../hooks/usePermissions';

/**
 * Wraps routes that require authentication.
 * Redirects to /login if not authenticated, storing return location safely.
 */
export function ProtectedRoute() {
  const { isAuthenticated, loading } = useAuth();
  const location = useLocation();

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
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <Outlet />;
}

/**
 * Wraps routes that require a specific capability.
 * Displays an in-place Access Denied state rather than redirect loops if the user lacks the capability.
 */
export function RoleRoute({ capability, fallback, children }) {
  const { isAuthenticated, loading } = useAuth();
  const { hasCapability } = usePermissions();
  const location = useLocation();

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
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (capability && !hasCapability(capability)) {
    if (fallback) return fallback;
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '60vh',
        padding: '2rem',
        textAlign: 'center',
        color: 'var(--color-text-primary)',
      }}>
        <h2 style={{ marginBottom: '0.5rem' }}>Access Denied</h2>
        <p style={{ color: 'var(--color-text-secondary)', maxWidth: '420px', lineHeight: 1.5 }}>
          You do not have permission ({capability}) to access this view. Switch to a role with appropriate access to proceed.
        </p>
      </div>
    );
  }

  return children || <Outlet />;
}
