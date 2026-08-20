import { motion } from 'framer-motion';
import './GlassCard.css';

export default function GlassCard({
  children,
  className = '',
  glow = false,
  hover = true,
  delay = 0,
  onClick,
}) {
  return (
    <motion.div
      className={`glass-card-component ${glow ? 'glow' : ''} ${hover ? 'hoverable' : ''} ${className}`}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay }}
      whileHover={hover ? { y: -4, transition: { duration: 0.2 } } : {}}
      onClick={onClick}
    >
      {children}
    </motion.div>
  );
}
