import { useAuth } from '../context/AuthContext';
import { useSession } from '../context/SessionContext';
import { PresenceState } from '../hooks/usePersonPresence';

// Visible, glanceable proof that presence detection is running -- lets you
// confirm the NO_PERSON -> PERSON_DETECTED -> CONVERSATION_ACTIVE state
// machine live (e.g. during a demo) without opening DevTools.
const STATE_META = {
  [PresenceState.NO_PERSON]: { label: 'No person', color: '#9ca3af', pulse: false },
  [PresenceState.PERSON_DETECTED]: { label: 'Person detected', color: '#f59e0b', pulse: true },
  [PresenceState.CONVERSATION_ACTIVE]: { label: 'Conversation active', color: '#22c55e', pulse: true },
};

export default function PresenceDebugBadge() {
  const { isAuthenticated } = useAuth();
  const { presenceState, presenceCameraError } = useSession();

  if (!isAuthenticated) return null;

  const meta = STATE_META[presenceState] || STATE_META[PresenceState.NO_PERSON];

  return (
    <div
      style={{
        position: 'fixed',
        top: 12,
        right: 12,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 12px',
        borderRadius: 999,
        background: 'rgba(15, 15, 20, 0.72)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        color: '#fff',
        fontSize: '0.75rem',
        lineHeight: 1,
        fontFamily: 'inherit',
        pointerEvents: 'none',
        border: '1px solid rgba(255,255,255,0.12)',
        whiteSpace: 'nowrap',
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: meta.color,
          boxShadow: meta.pulse ? `0 0 0 4px ${meta.color}33` : 'none',
          flexShrink: 0,
          transition: 'background 0.2s ease',
        }}
      />
      <span>
        {presenceCameraError ? `Presence camera error: ${presenceCameraError}` : meta.label}
      </span>
    </div>
  );
}
