import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import styles from './login.module.css';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const from = location.state?.from?.pathname;
  const targetDestination = (from && from !== '/login')
    ? `${from}${location.state?.from?.search || ''}`
    : '/';

  async function quickLogin(targetEmail, targetPass) {
    setEmail(targetEmail);
    setPassword(targetPass);
    setError('');
    setLoading(true);

    try {
      await login(targetEmail, targetPass);
      navigate(targetDestination, { replace: true });
    } catch (err) {
      const msg = err.data?.error?.message || err.data?.detail || err.message || 'Login failed';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(email, password);
      navigate(targetDestination, { replace: true });
    } catch (err) {
      const msg = err.data?.error?.message || err.data?.detail || err.message || 'Login failed';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <form className={styles.form} onSubmit={handleSubmit}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel} htmlFor="email">Email</label>
          <input
            id="email"
            className={styles.fieldInput}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.test"
            required
            autoComplete="email"
            autoFocus
          />
        </div>

        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel} htmlFor="password">Password</label>
          <input
            id="password"
            className={styles.fieldInput}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            required
            autoComplete="current-password"
          />
        </div>

        <button className={styles.submitBtn} type="submit" disabled={loading}>
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
      </form>

      <p className={styles.demoHint}>
        <strong>Quick Demo Login:</strong> Click any demo persona below to sign in instantly. An interactive Guide will open automatically.
      </p>
      <div className={styles.personaGrid}>
        <button
          type="button"
          className={styles.personaBtn}
          disabled={loading}
          onClick={() => quickLogin('maya.sharma@example.test', 'handoffscope-dev-2026')}
        >
          <strong>Maya Sharma</strong>
          <span className={styles.personaRole}>Project Lead</span>
        </button>

        <button
          type="button"
          className={styles.personaBtn}
          disabled={loading}
          onClick={() => quickLogin('kabir.singh@example.test', 'handoffscope-dev-2026')}
        >
          <strong>Kabir Singh</strong>
          <span className={styles.personaRole}>Reviewer</span>
        </button>

        <button
          type="button"
          className={styles.personaBtn}
          disabled={loading}
          onClick={() => quickLogin('aisha.khan@example.test', 'handoffscope-dev-2026')}
        >
          <strong>Aisha Khan</strong>
          <span className={styles.personaRole}>Successor</span>
        </button>

        <button
          type="button"
          className={styles.personaBtn}
          disabled={loading}
          onClick={() => quickLogin('arjun.patel@example.test', 'handoffscope-dev-2026')}
        >
          <strong>Arjun Patel</strong>
          <span className={styles.personaRole}>Departing Dev</span>
        </button>
      </div>

      <div className={styles.demoCredentials}>
        Password for all accounts: <code>handoffscope-dev-2026</code>
      </div>
    </div>
  );
}
