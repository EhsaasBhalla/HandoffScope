import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const ThemeContext = createContext(null);

const STORAGE_KEY = 'handoffscope-theme';

function getInitialTheme() {
  try {
    const stored = typeof window !== 'undefined' ? window.localStorage?.getItem(STORAGE_KEY) : null;
    if (stored === 'dark' || stored === 'light') return stored;
    if (typeof window !== 'undefined' && window.matchMedia) {
      return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
  } catch {
    // Ignore storage / privacy mode exceptions
  }
  return 'dark';
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(getInitialTheme);

  useEffect(() => {
    try {
      if (typeof document !== 'undefined') {
        document.documentElement.setAttribute('data-theme', theme);
      }
      if (typeof window !== 'undefined') {
        window.localStorage?.setItem(STORAGE_KEY, theme);
      }
    } catch {
      // Ignore storage quota / privacy mode errors
    }
  }, [theme]);

  const toggleTheme = useCallback((event) => {
    const nextTheme = theme === 'dark' ? 'light' : 'dark';

    // Circular reveal animation via View Transition API
    const prefersReducedMotion = typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false;

    if (typeof document === 'undefined' || !document.startViewTransition || prefersReducedMotion) {
      setThemeState(nextTheme);
      return;
    }

    // Get click coordinates for the reveal origin
    const innerW = typeof window !== 'undefined' ? window.innerWidth : 800;
    const innerH = typeof window !== 'undefined' ? window.innerHeight : 600;
    const x = event?.clientX ?? innerW / 2;
    const y = event?.clientY ?? innerH / 2;
    const endRadius = Math.hypot(
      Math.max(x, innerW - x),
      Math.max(y, innerH - y)
    );

    const transition = document.startViewTransition(() => {
      setThemeState(nextTheme);
    });

    transition.ready?.then(() => {
      document.documentElement.animate(
        {
          clipPath: [
            `circle(0px at ${x}px ${y}px)`,
            `circle(${endRadius}px at ${x}px ${y}px)`,
          ],
        },
        {
          duration: 500,
          easing: 'ease-in-out',
          pseudoElement: '::view-transition-new(root)',
        }
      );
    }).catch(() => {
      // View transition API not fully supported, theme already changed
    });
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
