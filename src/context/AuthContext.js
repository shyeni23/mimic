import { createContext, useContext, useEffect, useState } from 'react';
import { API_BASE_URL } from '../utils/api';

// Was a single flag set unconditionally on any login attempt -- AdminLogin.js
// called login() regardless of what was typed, so this never actually
// checked anything. Now it holds a real signed token from
// POST /api/auth/staff-login (see backend/app/services/auth.py), verified
// against the backend once on load so an expired or stale token (e.g. the
// backend restarted with a freshly-generated secret) doesn't silently leave
// someone "logged in" to a session the server no longer honors.
const TOKEN_KEY = 'mirrorai-staff-token';

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  // While the stored token is being verified, treat the app as not-yet-
  // decided rather than flashing the login screen then immediately past it.
  const [checking, setChecking] = useState(() => !!localStorage.getItem(TOKEN_KEY));

  useEffect(() => {
    if (!token) { setChecking(false); return; }
    let cancelled = false;
    fetch(`${API_BASE_URL}/api/auth/verify`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (cancelled) return;
        if (!res.ok) {
          localStorage.removeItem(TOKEN_KEY);
          setToken(null);
        }
      })
      .catch(() => { /* network hiccup -- keep the token, don't force a re-login over a blip */ })
      .finally(() => { if (!cancelled) setChecking(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = (newToken) => {
    localStorage.setItem(TOKEN_KEY, newToken);
    setToken(newToken);
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated: !!token, checking, token, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
