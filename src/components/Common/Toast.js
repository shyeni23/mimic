import { motion, AnimatePresence } from 'framer-motion';
import { RiCheckLine, RiCloseLine, RiInformationLine, RiErrorWarningLine } from 'react-icons/ri';
import './Toast.css';

const icons = {
  success: <RiCheckLine />,
  error: <RiErrorWarningLine />,
  info: <RiInformationLine />,
};

export default function Toast({ toasts = [], onDismiss }) {
  return (
    <div className="toast-container">
      <AnimatePresence>
        {toasts.map((toast) => (
          <motion.div
            key={toast.id}
            className={`toast toast-${toast.type || 'info'}`}
            initial={{ opacity: 0, y: -20, x: 20 }}
            animate={{ opacity: 1, y: 0, x: 0 }}
            exit={{ opacity: 0, x: 100 }}
            transition={{ type: 'spring', stiffness: 300, damping: 25 }}
          >
            <span className="toast-icon">{icons[toast.type] || icons.info}</span>
            <p className="toast-message">{toast.message}</p>
            <button className="toast-close" onClick={() => onDismiss(toast.id)}>
              <RiCloseLine />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
