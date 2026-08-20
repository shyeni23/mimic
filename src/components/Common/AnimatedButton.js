import { motion } from 'framer-motion';
import './AnimatedButton.css';

export default function AnimatedButton({
  children,
  variant = 'primary',
  size = 'medium',
  icon,
  onClick,
  disabled = false,
  fullWidth = false,
  className = '',
}) {
  return (
    <motion.button
      className={`animated-btn ${variant} ${size} ${fullWidth ? 'full-width' : ''} ${className}`}
      onClick={onClick}
      disabled={disabled}
      whileHover={{ scale: disabled ? 1 : 1.02 }}
      whileTap={{ scale: disabled ? 1 : 0.97 }}
    >
      <span className="btn-bg" />
      <span className="btn-content">
        {icon && <span className="btn-icon">{icon}</span>}
        {children}
      </span>
      <span className="btn-ripple" />
    </motion.button>
  );
}
