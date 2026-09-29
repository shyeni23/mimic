import { NavLink } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RiDashboardLine, RiBodyScanLine, RiSparklingLine, RiMessage3Line,
  RiShirtLine, RiCameraLine, RiHeartLine, RiShoppingBag3Line,
  RiUserLine, RiSettings4Line, RiCloseLine, RiCustomerService2Line
} from 'react-icons/ri';
import './Sidebar.css';

const iconMap = {
  RiDashboardLine: RiDashboardLine,
  RiBodyScanLine: RiBodyScanLine,
  RiSparklingLine: RiSparklingLine,
  RiMessage3Line: RiMessage3Line,
  RiShirtLine: RiShirtLine,
  RiCameraLine: RiCameraLine,
  RiHeartLine: RiHeartLine,
  RiShoppingBag3Line: RiShoppingBag3Line,
  RiUserLine: RiUserLine,
  RiSettings4Line: RiSettings4Line,
  RiCustomerService2Line: RiCustomerService2Line,
};

const navItems = [
  { path: '/dashboard', label: 'Dashboard', icon: 'RiDashboardLine' },
  { path: '/body-scanner', label: 'Body Scanner', icon: 'RiBodyScanLine' },
  { path: '/recommendations', label: 'Recommendations', icon: 'RiSparklingLine' },
  { path: '/stylist', label: 'AI Stylist', icon: 'RiMessage3Line' },
  { path: '/outfit-builder', label: 'Outfit Builder', icon: 'RiShirtLine' },
  { path: '/virtual-tryon', label: 'Virtual Try-On', icon: 'RiCameraLine' },
  { path: '/personalization', label: 'Personalization', icon: 'RiHeartLine' },
  { path: '/shopping', label: 'Shopping', icon: 'RiShoppingBag3Line' },
  { path: '/profile', label: 'Profile', icon: 'RiUserLine' },
  { path: '/staff-requests', label: 'Staff Assistance', icon: 'RiCustomerService2Line' },
  { path: '/settings', label: 'Settings', icon: 'RiSettings4Line' },
];

export default function Sidebar({ isOpen, onClose }) {
  return (
    <>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            className="sidebar-overlay"
            initial={{ opacity: 0, pointerEvents: 'none' }}
            animate={{ opacity: 1, pointerEvents: 'auto' }}
            exit={{ opacity: 0, pointerEvents: 'none' }}
            onClick={onClose}
          />
        )}
      </AnimatePresence>

      <motion.aside
        className={`sidebar ${isOpen ? 'open' : ''}`}
        initial={false}
      >
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <div className="logo-icon">
              <svg viewBox="0 0 40 40" fill="none">
                <rect width="40" height="40" rx="12" fill="url(#logoGrad)" />
                <path d="M12 20L18 14L24 20L18 26Z" fill="white" opacity="0.9" />
                <path d="M18 14L24 20L30 14L24 8Z" fill="white" opacity="0.6" />
                <defs>
                  <linearGradient id="logoGrad" x1="0" y1="0" x2="40" y2="40">
                    <stop stopColor="#6C63FF" />
                    <stop offset="1" stopColor="#00C2FF" />
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <div className="logo-text">
              <h2>Mirror<span>AI</span></h2>
              <p>Smart Fashion</p>
            </div>
          </div>
          <button className="sidebar-close" onClick={onClose}>
            <RiCloseLine />
          </button>
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item, i) => {
            const Icon = iconMap[item.icon];
            return (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
                onClick={onClose}
              >
                <motion.div
                  className="link-content"
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                >
                  <Icon className="link-icon" />
                  <span>{item.label}</span>
                </motion.div>
              </NavLink>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-pro-card">
            <div className="pro-glow" />
            <h4>Upgrade to Pro</h4>
            <p>Unlock AI styling features</p>
            <button className="pro-btn">Upgrade</button>
          </div>
        </div>
      </motion.aside>
    </>
  );
}
