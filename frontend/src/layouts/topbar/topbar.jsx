import { useState, useRef, useEffect } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { Sun, Moon, LogOut, User, ChevronRight, Compass } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { useAuth } from '../../context/AuthContext';
import styles from './topbar.module.css';

// Build breadcrumbs from pathname
function buildBreadcrumbs(pathname) {
  if (pathname === '/') return [{ label: 'Dashboard', path: '/' }];

  const segments = pathname.split('/').filter(Boolean);
  const crumbs = [{ label: 'Home', path: '/' }];

  let currentPath = '';
  for (const seg of segments) {
    currentPath += `/${seg}`;
    // Capitalise and prettify
    const label = seg
      .replace(/-/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
    crumbs.push({ label, path: currentPath });
  }
  return crumbs;
}

function getInitials(name) {
  if (!name) return '?';
  return name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

export function Topbar({ onOpenGuide }) {
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  const breadcrumbs = buildBreadcrumbs(location.pathname);

  // Close menu on outside click
  useEffect(() => {
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    }
    if (menuOpen) document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [menuOpen]);

  return (
    <header className={styles.topbar}>
      <div className={styles.left}>
        <nav className={styles.breadcrumbs}>
          {breadcrumbs.map((crumb, i) => (
            <span key={crumb.path} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              {i > 0 && <ChevronRight size={14} className={styles.separator} />}
              {i === breadcrumbs.length - 1 ? (
                <span className={styles.currentPage}>{crumb.label}</span>
              ) : (
                <Link to={crumb.path}>{crumb.label}</Link>
              )}
            </span>
          ))}
        </nav>
      </div>

      <div className={styles.right}>
        {/* Workspace Guide Button */}
        {onOpenGuide && (
          <button
            className={styles.guideBtn}
            onClick={onOpenGuide}
            title="Open Guide & Interactive Walkthrough"
          >
            <Compass size={16} className={styles.guideIcon} />
            <span className={styles.guideLabel}>Guide</span>
          </button>
        )}

        {/* Theme toggle */}
        <button
          className={styles.iconBtn}
          onClick={toggleTheme}
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>

        {/* User menu */}
        <div ref={menuRef} style={{ position: 'relative' }}>
          <button
            className={styles.userMenu}
            onClick={() => setMenuOpen((o) => !o)}
          >
            <div className={styles.avatar}>
              {getInitials(user?.display_name)}
            </div>
            <span className={styles.userName}>{user?.display_name || 'User'}</span>
          </button>

          {menuOpen && (
            <div className={styles.dropdownMenu}>
              <div style={{ padding: '8px 12px' }}>
                <div style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--weight-medium)' }}>
                  {user?.display_name}
                </div>
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                  {user?.email}
                </div>
              </div>
              <div className={styles.dropdownDivider} />
              <button
                className={styles.dropdownItem}
                onClick={() => { setMenuOpen(false); logout(); }}
              >
                <LogOut size={16} />
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
