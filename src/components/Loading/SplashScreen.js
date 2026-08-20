import { motion } from 'framer-motion';
import './SplashScreen.css';

export default function SplashScreen({ onComplete }) {
  return (
    <motion.div
      className="splash-screen"
      initial={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.8 }}
    >
      <div className="splash-bg">
        <div className="splash-particles">
          {Array.from({ length: 20 }).map((_, i) => (
            <div
              key={i}
              className="particle"
              style={{
                left: `${Math.random() * 100}%`,
                animationDelay: `${Math.random() * 5}s`,
                animationDuration: `${5 + Math.random() * 10}s`,
              }}
            />
          ))}
        </div>
      </div>

      <motion.div
        className="splash-content"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.8, delay: 0.2 }}
      >
        <motion.div
          className="splash-logo"
          animate={{ rotate: [0, 360] }}
          transition={{ duration: 20, repeat: Infinity, ease: 'linear' }}
        >
          <svg viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="splashGrad1" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#6C63FF" />
                <stop offset="100%" stopColor="#00C2FF" />
              </linearGradient>
              <linearGradient id="splashGrad2" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#8B5CF6" />
                <stop offset="100%" stopColor="#6C63FF" />
              </linearGradient>
            </defs>
            <circle cx="60" cy="60" r="55" stroke="url(#splashGrad1)" strokeWidth="2" fill="none" opacity="0.3" />
            <circle cx="60" cy="60" r="45" stroke="url(#splashGrad2)" strokeWidth="1.5" fill="none" opacity="0.2" />
            <path d="M40 60L55 45L70 60L55 75Z" fill="url(#splashGrad1)" />
            <path d="M55 45L70 60L85 45L70 30Z" fill="url(#splashGrad2)" opacity="0.7" />
          </svg>
        </motion.div>

        <motion.div
          className="splash-glow-ring"
          animate={{
            boxShadow: [
              '0 0 30px rgba(108, 99, 255, 0.3)',
              '0 0 60px rgba(108, 99, 255, 0.6), 0 0 90px rgba(0, 194, 255, 0.3)',
              '0 0 30px rgba(108, 99, 255, 0.3)',
            ],
          }}
          transition={{ duration: 2, repeat: Infinity }}
        />

        <motion.h1
          className="splash-title"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
        >
          Mirror<span>AI</span>
        </motion.h1>

        <motion.p
          className="splash-subtitle"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.9 }}
        >
          Your Personal Fashion Intelligence
        </motion.p>

        <motion.div
          className="splash-loader"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.2 }}
        >
          <div className="loader-bar">
            <motion.div
              className="loader-fill"
              initial={{ width: '0%' }}
              animate={{ width: '100%' }}
              transition={{ duration: 2.5, delay: 1.2, ease: 'easeInOut' }}
              onAnimationComplete={onComplete}
            />
          </div>
          <p className="loader-text">Initializing AI Fashion Engine...</p>
        </motion.div>
      </motion.div>
    </motion.div>
  );
}
