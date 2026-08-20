import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { motion } from 'framer-motion';
import Navbar from '../components/Navbar/Navbar';
import Sidebar from '../components/Sidebar/Sidebar';
import BottomNav from '../components/Navbar/BottomNav';
import Toast from '../components/Common/Toast';
import { useIsMobile } from '../hooks/useMediaQuery';
import { useSession } from '../context/SessionContext';
import './MainLayout.css';

export default function MainLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const isMobile = useIsMobile();
  const { toasts, dismissToast } = useSession();

  return (
    <div className="main-layout">
      <Sidebar isOpen={sidebarOpen || !isMobile} onClose={() => setSidebarOpen(false)} />
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
