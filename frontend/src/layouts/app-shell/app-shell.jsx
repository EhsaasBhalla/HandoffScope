import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from '../sidebar/sidebar';
import { Topbar } from '../topbar/topbar';
import { JudgeGuideModal } from '../../components/judge-guide-modal/judge-guide-modal';
import styles from './app-shell.module.css';

export function AppShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [guideOpen, setGuideOpen] = useState(() => {
    // Open automatically on login unless explicitly dismissed by user
    return localStorage.getItem('handoffscope_guide_dismissed') !== 'true';
  });

  return (
    <div className={styles.shell}>
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((c) => !c)}
      />
      <div className={`${styles.main} ${sidebarCollapsed ? styles.collapsed : ''}`}>
        <Topbar onOpenGuide={() => setGuideOpen(true)} />
        <main className={styles.content}>
          <Outlet />
        </main>
      </div>

      <JudgeGuideModal
        isOpen={guideOpen}
        onClose={() => setGuideOpen(false)}
      />
    </div>
  );
}
