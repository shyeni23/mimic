import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { motion } from 'framer-motion';
import Navbar from '../components/Navbar/Navbar';
import Sidebar from '../components/Sidebar/Sidebar';
import BottomNav from '../components/Navbar/BottomNav';
import Toast from '../components/Common/Toast';
import { useIsTablet } from '../hooks/useMediaQuery';
import { useSession } from '../context/SessionContext';
import './MainLayout.css';

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
    </div>
  );
}
