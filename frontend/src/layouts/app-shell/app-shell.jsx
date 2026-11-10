import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from '../sidebar/sidebar';
import { Topbar } from '../topbar/topbar';
import styles from './app-shell.module.css';

export function AppShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className={styles.shell}>
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((c) => !c)}
      />
      <div className={`${styles.main} ${sidebarCollapsed ? styles.collapsed : ''}`}>
        <Topbar />
        <main className={styles.content}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
