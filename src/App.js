import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';
import { ThemeProvider } from './context/ThemeContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import { SessionProvider } from './context/SessionContext';
import MainLayout from './layouts/MainLayout';
import SplashScreen from './components/Loading/SplashScreen';
import PresenceGate from './components/PresenceGate';
import PresenceDebugBadge from './components/PresenceDebugBadge';
import AdminLogin from './pages/AdminLogin';
import Dashboard from './pages/Dashboard';
import BodyScanner from './pages/BodyScanner';
import AnalysisResults from './pages/AnalysisResults';
import Recommendations from './pages/Recommendations';
import AIStylist from './pages/AIStylist';
import OutfitBuilder from './pages/OutfitBuilder';
import VirtualTryOn from './pages/VirtualTryOn';
import Personalization from './pages/Personalization';
import Shopping from './pages/Shopping';
import Profile from './pages/Profile';
import Settings from './pages/Settings';
import './styles/global.css';

function AppRoutes() {
  const { isAuthenticated } = useAuth();

  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="*" element={<AdminLogin />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<MainLayout />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/body-scanner" element={<BodyScanner />} />
        <Route path="/analysis-results" element={<AnalysisResults />} />
        <Route path="/recommendations" element={<Recommendations />} />
        <Route path="/stylist" element={<AIStylist />} />
        <Route path="/outfit-builder" element={<OutfitBuilder />} />
        <Route path="/virtual-tryon" element={<VirtualTryOn />} />
        <Route path="/personalization" element={<Personalization />} />
        <Route path="/shopping" element={<Shopping />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

function App() {
  const [showSplash, setShowSplash] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => setShowSplash(false), 3500);
    return () => clearTimeout(timer);
  }, []);

  return (
    <ThemeProvider>
      <AuthProvider>
        <SessionProvider>
          <Router>
            {showSplash ? (
              <SplashScreen onComplete={() => setShowSplash(false)} />
            ) : (
              <>
                <PresenceGate />
                <PresenceDebugBadge />
                <AppRoutes />
              </>
            )}
          </Router>
        </SessionProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
