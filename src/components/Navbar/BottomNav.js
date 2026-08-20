import { NavLink } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  RiDashboardLine, RiSparklingLine, RiMessage3Line,
  RiShoppingBag3Line, RiUserLine
} from 'react-icons/ri';
import './BottomNav.css';

const items = [
  { path: '/dashboard', label: 'Home', Icon: RiDashboardLine },
  { path: '/recommendations', label: 'Style', Icon: RiSparklingLine },
  { path: '/stylist', label: 'Chat', Icon: RiMessage3Line },
  { path: '/shopping', label: 'Shop', Icon: RiShoppingBag3Line },
  { path: '/profile', label: 'Profile', Icon: RiUserLine },
];

export default function BottomNav() {
  return (
    <nav className="bottom-nav">
      {items.map(({ path, label, Icon }) => (
        <NavLink
          key={path}
          to={path}
          className={({ isActive }) => `bottom-nav-item ${isActive ? 'active' : ''}`}
        >
          {({ isActive }) => (
            <>
              {isActive && (
                <motion.div
                  className="bottom-nav-indicator"
                  layoutId="bottomNavIndicator"
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                />
              )}
              <Icon className="bottom-nav-icon" />
              <span>{label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
