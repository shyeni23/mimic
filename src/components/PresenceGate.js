import { useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useSession } from '../context/SessionContext';
import { PresenceState } from '../hooks/usePersonPresence';

/**
 * Bridges CAMERA presence detection to the CONVERSATION module.
 *
 * This is the only place presence state turns into an app action -- it does
 * not know or care how the conversation itself works (STT/LLM/TTS, all of
 * that lives in AIStylist.js / the backend agent). It just hands off to the
 * page that owns the conversation, exactly once per detected person, by
 * navigating there when presence flips to CONVERSATION_ACTIVE. AIStylist.js
 * itself auto-arms hands-free listening from the same shared presenceState,
 * so this is purely a "bring the right screen into view" hop.
 */
export default function PresenceGate() {
  const { presenceState } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const prevStateRef = useRef(presenceState);

  useEffect(() => {
    const prev = prevStateRef.current;
    prevStateRef.current = presenceState;

    if (presenceState === PresenceState.CONVERSATION_ACTIVE && prev !== PresenceState.CONVERSATION_ACTIVE) {
      if (location.pathname !== '/stylist') {
        navigate('/stylist');
      }
    }
  }, [presenceState, location.pathname, navigate]);

  return null;
}
