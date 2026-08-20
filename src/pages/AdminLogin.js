import { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { RiGoogleFill, RiMailLine, RiLockLine, RiEyeLine, RiEyeOffLine, RiShieldStarLine } from 'react-icons/ri';
import AnimatedButton from '../components/Common/AnimatedButton';
import { useAuth } from '../context/AuthContext';
import './AdminLogin.css';

export default function AdminLogin() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [showPassword, setShowPassword] = useState(false);
  const [formData, setFormData] = useState({ email: '', password: '' });

  const handleSubmit = (e) => {
    e.preventDefault();
    login();
    navigate('/dashboard');
  };

  const handleGoogleLogin = () => {
    login();
    navigate('/dashboard');
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

        <motion.button
          className="google-btn"
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={handleGoogleLogin}
        >
          <RiGoogleFill />
          Continue with Google
        </motion.button>

        <div className="login-divider">
          <span>or</span>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <label>Email</label>
            <div className="input-wrapper">
              <RiMailLine className="input-icon" />
              <input
                type="email"
                placeholder="Enter admin email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              />
            </div>
          </div>

          <div className="input-group">
            <label>Password</label>
            <div className="input-wrapper">
              <RiLockLine className="input-icon" />
              <input
                type={showPassword ? 'text' : 'password'}
                placeholder="Enter admin password"
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

          <div className="login-options">
            <button type="button" className="forgot-link">Forgot password?</button>
          </div>

          <AnimatedButton fullWidth size="large" className="submit-btn">
            Start System
          </AnimatedButton>
        </form>

        <p className="login-footnote">
          For shop staff only. Customers can use the mirror without signing in.
        </p>
      </motion.div>
    </div>
  );
}
