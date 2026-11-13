import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../context/ThemeContext';
import { User, Moon, Sun, Cpu, Server } from 'lucide-react';
import styles from './settings.module.css';

export default function SettingsPage() {
  const { user } = useAuth();
  const { theme, toggleTheme } = useTheme();

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h2>Settings & Platform Configuration</h2>
        <p className={styles.subtitle}>
          Manage personal preferences, inspect security parameters, and review system configuration.
        </p>
      </div>

      {/* User Profile Card */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <User size={20} color="var(--color-primary)" />
          <h3>Active Profile</h3>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>Display Name</div>
            <div className={styles.sublabel}>Your visible name across audit logs and reviews</div>
          </div>
          <div className={styles.value}>{user?.display_name || '—'}</div>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>Email Address</div>
            <div className={styles.sublabel}>Used for system authentication and notifications</div>
          </div>
          <div className={styles.value}>{user?.email || '—'}</div>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>Account Status</div>
            <div className={styles.sublabel}>Authentication status and session validity</div>
          </div>
          <div>
            <span className={`${styles.badge} ${styles.badgeSuccess}`}>
              {user?.is_active ? 'Active & Verified' : 'Inactive'}
            </span>
          </div>
        </div>
      </div>

      {/* Appearance & Interface Card */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          {theme === 'dark' ? <Moon size={20} color="var(--color-primary)" /> : <Sun size={20} color="var(--color-primary)" />}
          <h3>Interface & Appearance</h3>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>Color Theme</div>
            <div className={styles.sublabel}>
              Warm Charcoal dark mode or warm paper light mode with circular View Transition ripple
            </div>
          </div>
          <button type="button" className={styles.toggleBtn} onClick={toggleTheme}>
            {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
            <span>Switch to {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}</span>
          </button>
        </div>
      </div>

      {/* AI Extraction & Evidence Configuration */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <Cpu size={20} color="var(--color-primary)" />
          <h3>Knowledge Reconstruction & AI Engine</h3>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>Extraction Provider Mode</div>
            <div className={styles.sublabel}>Configured LLM reasoning engine</div>
          </div>
          <div className={styles.monoValue}>Mock LLM / Cloud Gemini 1.5 Flash</div>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>Grounding Citation Guarantee</div>
            <div className={styles.sublabel}>All extracted claims must cite verified source IDs</div>
          </div>
          <div>
            <span className={`${styles.badge} ${styles.badgeSuccess}`}>Strict Enforcement Active</span>
          </div>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>Unknown Output Policy</div>
            <div className={styles.sublabel}>Permits explicit unknown state for undocumented gaps</div>
          </div>
          <div>
            <span className={`${styles.badge} ${styles.badgeSuccess}`}>Enabled</span>
          </div>
        </div>
      </div>

      {/* Storage & Environment Diagnostics */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <Server size={20} color="var(--color-primary)" />
          <h3>Platform & Infrastructure Diagnostics</h3>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>Supported Document Formats</div>
            <div className={styles.sublabel}>Technical specifications, runbooks, and contracts</div>
          </div>
          <div className={styles.monoValue}>PDF, DOCX, Markdown (.md), Plain Text (.txt)</div>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>Maximum Upload File Size</div>
            <div className={styles.sublabel}>Single-document ingestion limit</div>
          </div>
          <div className={styles.value}>50 MB</div>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>Database Compatibility Engine</div>
            <div className={styles.sublabel}>SQLAlchemy 2.0 dual dialect engine</div>
          </div>
          <div className={styles.monoValue}>PostgreSQL (JSONB native) / SQLite (Dev)</div>
        </div>

        <div className={styles.row}>
          <div>
            <div className={styles.label}>API Version & Gateway</div>
            <div className={styles.sublabel}>REST API Documentation at /api/v1/docs</div>
          </div>
          <div className={styles.monoValue}>v1.0 (Production Release)</div>
        </div>
      </div>
    </div>
  );
}
