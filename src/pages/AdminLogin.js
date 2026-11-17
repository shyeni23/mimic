import { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { RiMailLine, RiLockLine, RiEyeLine, RiEyeOffLine, RiShieldStarLine, RiErrorWarningLine } from 'react-icons/ri';
import AnimatedButton from '../components/Common/AnimatedButton';
import { useAuth } from '../context/AuthContext';
import { API_BASE_URL } from '../utils/api';
import './AdminLogin.css';

export default function AdminLogin() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [showPassword, setShowPassword] = useState(false);
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Used to call login() unconditionally on any submit -- no backend check
  // existed at all, so any text in either field opened the mirror. This now
  // posts to the real endpoint (backend/app/services/auth.py) and only
  // proceeds on a genuine 200 with a signed token.
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.username.trim() || !formData.password) {
      setError('Enter both a username and a password.');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/staff-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: formData.username.trim(), password: formData.password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.detail || 'Sign-in failed.');
        return;
      }
      login(data.token);
      navigate('/dashboard');
    } catch (err) {
      setError("Couldn't reach the mirror's server -- check it's running.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-bg">
        <div className="login-orb login-orb-1" />
        <div className="login-orb login-orb-2" />
        <div className="login-particles">
          {Array.from({ length: 15 }).map((_, i) => (
            <div
              key={i}
              className="particle"
              style={{
                left: `${Math.random() * 100}%`,
                animationDelay: `${Math.random() * 5}s`,
                animationDuration: `${6 + Math.random() * 8}s`,
              }}
            />
          ))}
        </div>
      </div>

      <motion.div
        className="login-card"
        initial={{ opacity: 0, y: 30, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6 }}
      >
        <div className="login-header">
          <div className="login-logo">
            <svg viewBox="0 0 40 40" fill="none">
              <rect width="40" height="40" rx="12" fill="url(#loginGrad)" />
              <path d="M12 20L18 14L24 20L18 26Z" fill="white" opacity="0.9" />
              <path d="M18 14L24 20L30 14L24 8Z" fill="white" opacity="0.6" />
              <defs>
                <linearGradient id="loginGrad" x1="0" y1="0" x2="40" y2="40">
                  <stop stopColor="#6C63FF" />
                  <stop offset="1" stopColor="#00C2FF" />
                </linearGradient>
              </defs>
            </svg>
          </div>
          <span className="admin-badge">
            <RiShieldStarLine /> Admin Access
          </span>
          <h2>Start Your Shift</h2>
          <p>Sign in to power on the Smart Mirror</p>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <label>Username</label>
            <div className="input-wrapper">
              <RiMailLine className="input-icon" />
              <input
                type="text"
                autoComplete="username"
                placeholder="Staff username"
                value={formData.username}
                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
              />
            </div>
          </div>

          <div className="input-group">
            <label>Password</label>
            <div className="input-wrapper">
              <RiLockLine className="input-icon" />
              <input
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                placeholder="Enter staff password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword(!showPassword)}
              >
                {showPassword ? <RiEyeOffLine /> : <RiEyeLine />}
              </button>
            </div>
          </div>

          {error && (
            <p className="login-error">
              <RiErrorWarningLine /> {error}
            </p>
          )}

          <AnimatedButton fullWidth size="large" className="submit-btn" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Start System'}
          </AnimatedButton>
        </form>

        <p className="login-footnote">
          For shop staff only. Customers can use the mirror without signing in.
        </p>
      </motion.div>
    </div>
  );
}
