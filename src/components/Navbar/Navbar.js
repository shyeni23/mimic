import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { RiSearchLine, RiNotification3Line, RiMoonLine, RiSunLine, RiMenuLine } from 'react-icons/ri';
import { useTheme } from '../../context/ThemeContext';
import './Navbar.css';

export default function Navbar({ onMenuToggle }) {
  const { theme, toggleTheme } = useTheme();
  const [showNotifications, setShowNotifications] = useState(false);

  const notifications = [
    { id: 1, text: 'New outfit recommendation ready', time: '2m ago', unread: true },
    { id: 2, text: 'Your style analysis is complete', time: '15m ago', unread: true },
    { id: 3, text: 'Trending: Summer Collection 2026', time: '1h ago', unread: false },
  ];

  return (
    <nav className="navbar">
      <div className="navbar-left">
        <motion.button
          className="menu-toggle"
          onClick={onMenuToggle}
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
        >
          <RiMenuLine />
        </motion.button>
        <div className="navbar-search">
          <RiSearchLine />
          <input type="text" placeholder="Search styles, brands, trends..." />
        </div>
      </div>

      <div className="navbar-right">
        <motion.button
          className="nav-icon-btn"
          onClick={toggleTheme}
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
        >
          <AnimatePresence mode="wait">
            <motion.span
              key={theme}
              initial={{ rotate: -90, opacity: 0 }}
              animate={{ rotate: 0, opacity: 1 }}
              exit={{ rotate: 90, opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              {theme === 'dark' ? <RiSunLine /> : <RiMoonLine />}
            </motion.span>
          </AnimatePresence>
        </motion.button>

        <div className="notification-wrapper">
          <motion.button
            className="nav-icon-btn"
            onClick={() => setShowNotifications(!showNotifications)}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.9 }}
          >
            <RiNotification3Line />
            <span className="notification-badge">2</span>
          </motion.button>

          <AnimatePresence>
            {showNotifications && (
              <motion.div
                className="notification-dropdown glass-card"
                initial={{ opacity: 0, y: 10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 10, scale: 0.95 }}
              >
                <h4>Notifications</h4>
                {notifications.map((n) => (
                  <div key={n.id} className={`notification-item ${n.unread ? 'unread' : ''}`}>
                    <p>{n.text}</p>
                    <span>{n.time}</span>
                  </div>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <motion.div
          className="nav-avatar"
          whileHover={{ scale: 1.05 }}
        >
          <div className="avatar-placeholder">AI</div>
        </motion.div>
      </div>
    </nav>
  );
}
