import { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import Navbar from '../components/Navbar/Navbar';
import Sidebar from '../components/Sidebar/Sidebar';
import BottomNav from '../components/Navbar/BottomNav';
import Toast from '../components/Common/Toast';
import { useIsTablet } from '../hooks/useMediaQuery';
import { useSession } from '../context/SessionContext';
import { useAriaAction } from '../utils/ariaBus';
import './MainLayout.css';

// Shown for "help" / "what can I say?" -- the mirror is touchless, so the
// customer needs to see what they can say.
const HELP_EXAMPLES = [
  '"Show me sarees for a wedding"',
  '"Like the second one"',
  '"Add the first one to my cart"',
  '"Scroll down" / "Go back"',
  '"Show my cart" / "What\'s my total?"',
  '"Show only bags" / "Clear filters"',
  '"Stop talking" / "Mute your voice"',
  '"Thanks" (ends the chat)',
];
const CONFIRM_TIMEOUT_MS = 20000;

export default function MainLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Sidebar.css collapses to a slide-in drawer + backdrop at max-width:1024px
  // (not 768px) -- this must match that breakpoint exactly, otherwise any
  // viewport in the 769-1024px gap gets isOpen=true (desktop-style, correct)
  // AND the CSS still renders the mobile backdrop underneath it (since the
  // CSS thinks it's in drawer mode), which silently blocks every click to
  // the page. Was useIsMobile() (768px) -- confirmed live that a 1024px-wide
  // viewport froze the entire app (chat input, buttons, everything) behind
  // an invisible full-page overlay.
  const isCompact = useIsTablet();
  const { toasts, dismissToast } = useSession();
  const [confirmPrompt, setConfirmPrompt] = useState(null);
  const [helpOpen, setHelpOpen] = useState(false);

  useAriaAction(['toggle_sidebar', 'show_confirmation', 'hide_confirmation', 'show_help'], (payload, type) => {
    if (type === 'toggle_sidebar') {
      setSidebarOpen((open) => (payload.state === 'open' ? true : payload.state === 'close' ? false : !open));
    } else if (type === 'show_confirmation') {
      setConfirmPrompt(payload.prompt || 'Are you sure?');
    } else if (type === 'hide_confirmation') {
      setConfirmPrompt(null);
    } else if (type === 'show_help') {
      setHelpOpen(true);
    }
  });

  // The confirmation expires on the backend after 20s; hide the banner too.
  useEffect(() => {
    if (!confirmPrompt) return undefined;
    const t = setTimeout(() => setConfirmPrompt(null), CONFIRM_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [confirmPrompt]);

  useEffect(() => {
    if (!helpOpen) return undefined;
    const t = setTimeout(() => setHelpOpen(false), 15000);
    return () => clearTimeout(t);
  }, [helpOpen]);

  return (
    <div className="main-layout">
      <Sidebar isOpen={sidebarOpen || !isCompact} onClose={() => setSidebarOpen(false)} />
      <div className="main-content">
        <Navbar onMenuToggle={() => setSidebarOpen(!sidebarOpen)} />
        <motion.main
          className="page-content"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3 }}
        >
          <Outlet />
        </motion.main>
      </div>
      <BottomNav />
      <Toast toasts={toasts} onDismiss={dismissToast} />

      <AnimatePresence>
        {confirmPrompt && (
          <motion.div
            className="voice-confirm-banner"
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
          >
            <p>{confirmPrompt}</p>
            <span>Say <strong>"yes"</strong> or <strong>"no"</strong></span>
          </motion.div>
        )}
        {helpOpen && (
          <motion.div
            className="voice-help-card"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            onClick={() => setHelpOpen(false)}
          >
            <h3>You can say…</h3>
            <ul>{HELP_EXAMPLES.map((e) => <li key={e}>{e}</li>)}</ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
