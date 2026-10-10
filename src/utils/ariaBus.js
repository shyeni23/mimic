// Aria action bus: delivers voice actions to whichever screen owns them.
//
// VoiceAgentContext handles global actions itself (scroll, cart, likes...)
// and forwards page-local ones (filters, try-on controls, item focus...) here.
// A screen subscribes with useAriaAction(['set_category_filter', ...], fn).
//
// Actions are also kept for a few seconds so a page that mounts right after
// Aria navigated to it ("show the bags filter" from the dashboard) still
// receives the action that caused the navigation.
import { useEffect, useRef } from 'react';

const EVENT = 'aria-action';
const REPLAY_MS = 4000;
let recent = [];

export function emitAriaAction(action) {
  const entry = { ...action, _at: Date.now(), _handled: false };
  recent = [...recent.filter((a) => Date.now() - a._at < REPLAY_MS), entry];
  window.dispatchEvent(new CustomEvent(EVENT, { detail: entry }));
}

export function useAriaAction(types, handler) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  const key = types.join('|');

  useEffect(() => {
    const wanted = new Set(key.split('|'));
    const deliver = (action) => {
      if (!wanted.has(action.type)) return;
      action._handled = true;
      handlerRef.current(action.payload || {}, action.type);
    };
    // Replay anything that arrived just before this screen mounted.
    recent
      .filter((a) => !a._handled && Date.now() - a._at < REPLAY_MS)
      .forEach(deliver);
    const onEvent = (e) => deliver(e.detail);
    window.addEventListener(EVENT, onEvent);
    return () => window.removeEventListener(EVENT, onEvent);
  }, [key]);
}
