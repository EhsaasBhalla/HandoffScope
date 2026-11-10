import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import styles from './login.module.css';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(email, password);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.data?.error?.message || err.message || 'Login failed');
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

      <p className={styles.demoHint}>Demo environment — use any seeded account</p>
      <div className={styles.demoCredentials}>
        maya.sharma@example.test / handoffscope-dev-2026
      </div>
    </div>
  );
}
