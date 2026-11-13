import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { authApi } from '../api/auth.api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const queryClient = useQueryClient();

  // On mount, try to get current user from cookie/Bearer session (401 triggers silent refresh automatically)
  useEffect(() => {
    let cancelled = false;
    authApi.me()
      .then((data) => {
        if (!cancelled) setUser(data);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    const handleExpired = () => {
      if (!cancelled) {
        queryClient.clear();
        setUser(null);
      }
    };
    if (typeof window !== 'undefined') {
      window.addEventListener('handoffscope:auth-expired', handleExpired);
    }
    return () => {
      cancelled = true;
      if (typeof window !== 'undefined') {
        window.removeEventListener('handoffscope:auth-expired', handleExpired);
      }
    };
  }, [queryClient]);

  const login = useCallback(async (email, password) => {
    const data = await authApi.login(email, password);
    queryClient.clear();
    setUser(data?.user || data);
    return data;
  }, [queryClient]);

  const switchPersona = useCallback(async (email, password = 'handoffscope-dev-2026') => {
    return login(email, password);
  }, [login]);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      queryClient.clear();
      setUser(null);
    }
  }, [queryClient]);

  const value = {
    user,
    loading,
    isAuthenticated: !!user,
    login,
    switchPersona,
    logout,
    setUser,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
