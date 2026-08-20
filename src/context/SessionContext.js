import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { apiPostJSON, apiPost } from '../utils/api';
import { useAuth } from './AuthContext';
import { usePersonPresence, PresenceState } from '../hooks/usePersonPresence';

const SessionContext = createContext();

export function SessionProvider({ children }) {
  const { isAuthenticated } = useAuth();

  // Camera-based person-presence detection: a single global camera + state
  // machine (NO_PERSON -> PERSON_DETECTED -> CONVERSATION_ACTIVE), started
  // once the mirror app is up and running, independent of whatever page is
  // currently mounted. See usePersonPresence for the debouncing that keeps
  // it from re-triggering on every poll while the same person stays in view.
  const { presenceState, cameraError: presenceCameraError } = usePersonPresence({ enabled: isAuthenticated });

  const [sessionId, setSessionId] = useState(null);
  const [scanData, setScanData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Shared state for hands-free agent actions (Module 2, Phase B) -- the chat
  // agent can drive these pages directly via /api/chat's `actions[]`, not just
  // reply with text. See AIStylist.js's handleActions().
  const [pendingRecommendations, setPendingRecommendations] = useState(null);
  const [highlightedItemId, setHighlightedItemId] = useState(null);
  const [cartItems, setCartItems] = useState([]);
  const [toasts, setToasts] = useState([]);
  const [pendingOutfitActions, setPendingOutfitActions] = useState([]);

  const addToCart = useCallback((itemId) => {
    setCartItems((prev) => (prev.includes(itemId) ? prev : [...prev, itemId]));
  }, []);

  const pendingOutfitActionsRef = useRef([]);
  pendingOutfitActionsRef.current = pendingOutfitActions;

  const queueOutfitActions = useCallback((actions) => {
    setPendingOutfitActions((prev) => [...prev, ...actions]);
  }, []);

  const consumeOutfitActions = useCallback(() => {
    const actions = pendingOutfitActionsRef.current;
    if (actions.length > 0) setPendingOutfitActions([]);
    return actions;
  }, []);

  const showToast = useCallback((message, type = 'info') => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Proactive agent events (Module 2 build guide): the agent can react to
  // system events (scan finished, item stared at too long, idle on
  // recommendations...) without the user saying anything first. Any page can
  // call this -- it shows a toast with Aria's reaction and speaks it aloud.
  // sessionIdRef avoids re-creating fireAgentEvent (and re-triggering effects
  // that depend on it) every time sessionId changes.
  const sessionIdRef = useRef(sessionId);
  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);
  const inFlightEventsRef = useRef(new Set());

  const fireAgentEvent = useCallback(async (event, role = 'customer') => {
    const sid = sessionIdRef.current;
    if (!sid || inFlightEventsRef.current.has(event)) return;
    inFlightEventsRef.current.add(event);
    try {
      const data = await apiPostJSON('/api/agent/event', { session_id: sid, event, role });
      if (data.reply) {
        showToast(data.reply, 'info');
        try {
          const res = await apiPost('/api/voice/tts', { text: data.reply });
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          const audio = new Audio(url);
          audio.onended = () => URL.revokeObjectURL(url);
          audio.onerror = () => URL.revokeObjectURL(url);
          audio.play();
        } catch (ttsErr) {
          console.error('[agent-event] TTS playback failed:', ttsErr);
        }
      }
      for (const action of data.actions || []) {
        if (action.type === 'show_recommendations') {
          setPendingRecommendations(action.payload?.results || []);
        } else if (action.type === 'show_item') {
          setHighlightedItemId(action.payload?.item_id || null);
        } else if (action.type === 'add_to_cart') {
          addToCart(action.payload?.item_id);
        }
      }
    } catch (err) {
      console.error(`[agent-event] ${event} failed:`, err);
    } finally {
      inFlightEventsRef.current.delete(event);
    }
  }, [showToast, addToCart, setPendingRecommendations, setHighlightedItemId]);

  // Shared by the initial app-boot session and every later resetSession()
  // call -- returns the new session's id so callers (e.g. the presence ->
  // conversation bridge below) can chain work that needs it.
  const createSession = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiPostJSON('/api/session');
      setSessionId(data.id);
      setLoading(false);
      return data.id;
    } catch (err) {
      setError(err.message);
      setLoading(false);
      throw err;
    }
  }, []);

  useEffect(() => {
    createSession().catch(() => {}); // error already captured in state above
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resetSession = useCallback(() => {
    setScanData(null);
    return createSession();
  }, [createSession]);

  // ---------------- Presence -> conversation session (Module 2 hand-off) ----------------
  // person_detected -> create session -> initialize conversation state -> start
  // conversational agent -> LLM-generated greeting. This is the ONLY place that
  // chain runs, gated on the presence state machine actually transitioning into
  // CONVERSATION_ACTIVE (not on every render/poll), so one detected person means
  // exactly one new session and exactly one greeting call -- never a flood of
  // LLM requests.
  const [conversationGreeting, setConversationGreeting] = useState(null);
  const conversationInFlightRef = useRef(false);

  const startConversationSession = useCallback(async () => {
    if (conversationInFlightRef.current) return;
    conversationInFlightRef.current = true;
    setConversationGreeting(null); // clear any previous customer's greeting immediately
    try {
      const newSessionId = await resetSession(); // create session + initialize conversation state (fresh scanData)
      const data = await apiPostJSON('/api/agent/event', {
        session_id: newSessionId,
        event: 'conversation_start',
        role: 'customer',
      });
      setConversationGreeting({ sessionId: newSessionId, reply: data.reply, actions: data.actions || [] });
    } catch (err) {
      console.error('[conversation] failed to start:', err);
      setConversationGreeting({
        sessionId: sessionIdRef.current,
        reply: "Hi, welcome! I'm having a little trouble getting started -- give me a moment.",
        actions: [],
      });
    } finally {
      conversationInFlightRef.current = false;
    }
  }, [resetSession]);

  const prevPresenceStateRef = useRef(presenceState);
  useEffect(() => {
    const prev = prevPresenceStateRef.current;
    prevPresenceStateRef.current = presenceState;
    if (presenceState === PresenceState.CONVERSATION_ACTIVE && prev !== PresenceState.CONVERSATION_ACTIVE) {
      startConversationSession();
    }
  }, [presenceState, startConversationSession]);

  return (
    <SessionContext.Provider
      value={{
        sessionId, scanData, setScanData, loading, error, resetSession,
        pendingRecommendations, setPendingRecommendations,
        highlightedItemId, setHighlightedItemId,
        cartItems, addToCart,
        pendingOutfitActions, queueOutfitActions, consumeOutfitActions,
        toasts, showToast, dismissToast,
        fireAgentEvent,
        presenceState, presenceCameraError,
        conversationGreeting,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export const useSession = () => useContext(SessionContext);
