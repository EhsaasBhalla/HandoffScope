import { Outlet } from 'react-router-dom';
import styles from './auth-layout.module.css';

export function AuthLayout() {
  return (
    <div className={styles.authLayout}>
      <div className={styles.authCard}>
        <div className={styles.authHeader}>
          <div className={styles.authLogo}>
            <span className={styles.authLogoText}>H</span>
          </div>
          <h1 className={styles.authTitle}>HandoffScope</h1>
          <p className={styles.authSubtitle}>Evidence-led project handover</p>
        </div>
        <Outlet />
      </div>
    </div>
  );
}
