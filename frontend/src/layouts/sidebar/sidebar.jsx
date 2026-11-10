import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FolderKanban,
  FileStack,
  GitBranch,
  Clock,
  HelpCircle,
  CheckSquare,
  Users,
  Eye,
  ScrollText,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import { usePermissions } from '../../hooks/usePermissions';
import styles from './sidebar.module.css';

const NAV_SECTIONS = [
  {
    label: 'Overview',
    items: [
      { to: '/', icon: LayoutDashboard, label: 'Dashboard', capability: 'workspace.view' },
      { to: '/projects', icon: FolderKanban, label: 'Projects', capability: 'project.view' },
      { to: '/cases', icon: FileStack, label: 'Handover Cases', capability: 'case.view' },
    ],
  },
  {
    label: 'Evidence',
    items: [
      { to: '/sources', icon: GitBranch, label: 'Sources', capability: 'source.view' },
      { to: '/timeline', icon: Clock, label: 'Timeline', capability: 'timeline.view' },
    ],
  },
  {
    label: 'Workflow',
    items: [
      { to: '/questions', icon: HelpCircle, label: 'Questions', capability: 'question.view' },
      { to: '/review', icon: CheckSquare, label: 'Review Queue', capability: 'review.view' },
    ],
  },
  {
    label: 'Access',
    items: [
      { to: '/people', icon: Users, label: 'People & Access', capability: 'project.manage' },
      { to: '/successor', icon: Eye, label: 'Successor View', capability: 'successor.view' },
    ],
  },
  {
    label: 'Admin',
    items: [
      { to: '/audit', icon: ScrollText, label: 'Audit Log', capability: 'audit.view' },
      { to: '/settings', icon: Settings, label: 'Settings', capability: 'settings.manage' },
    ],
  },
];

export function Sidebar({ collapsed, onToggle }) {
  const { hasCapability } = usePermissions();

  // Filter sections and items based on current user capabilities
  const visibleSections = NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => hasCapability(item.capability)),
  })).filter((section) => section.items.length > 0);

  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ''}`}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.logo}>
          <span className={styles.logoIcon}>H</span>
        </div>
        <span className={styles.brandName}>HandoffScope</span>
      </div>

      {/* Navigation */}
      <nav className={styles.nav}>
        {visibleSections.map((section) => (
          <div key={section.label} className={styles.section}>
            <div className={styles.sectionLabel}>{section.label}</div>
            {section.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `${styles.navItem} ${isActive ? styles.active : ''}`
                }
                title={collapsed ? item.label : undefined}
              >
                <item.icon className={styles.navItemIcon} size={20} />
                <span className={styles.navItemLabel}>{item.label}</span>
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* Footer toggle */}
      <div className={styles.footer}>
        <button className={styles.toggleBtn} onClick={onToggle} title="Toggle sidebar">
          {collapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
        </button>
      </div>
    </aside>
  );
}
