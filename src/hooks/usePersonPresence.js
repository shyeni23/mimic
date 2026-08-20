import { useEffect, useRef, useState, useCallback } from 'react';
import { apiPostJSON } from '../utils/api';

/**
 * Global person-presence detector.
 *
 * Reuses the EXISTING /api/vision/presence endpoint (MediaPipe Pose, see
 * backend/app/routers/vision.py::presence()) -- this hook does no vision
 * work of its own, it just owns the camera lifecycle + polling cadence + a
 * small debounced state machine layered on top of that endpoint's yes/no
 * answer.
 *
 * This is CAMERA MONITORING ONLY. It has no idea what a microphone, STT, an
 * LLM, or TTS are -- callers (see components/PresenceGate.js) decide what
 * "trigger the conversational system" means once presence flips active.
 */
export const PresenceState = {
  NO_PERSON: 'NO_PERSON',
  PERSON_DETECTED: 'PERSON_DETECTED',
  CONVERSATION_ACTIVE: 'CONVERSATION_ACTIVE',
};

const POLL_MS = 1500;               // presence check is cheap -- see vision.py's own "poll every 1-2s" guidance
const PRESENT_CONFIRM_STREAK = 2;   // consecutive positive polls required before starting a conversation
const ABSENT_CONFIRM_STREAK = 3;    // consecutive negative polls required before ending one
const DETECTED_HOLD_MS = 600;       // how long PERSON_DETECTED is held before flipping to CONVERSATION_ACTIVE

export function usePersonPresence({ enabled = true } = {}) {
  const [presenceState, setPresenceState] = useState(PresenceState.NO_PERSON);
  const [cameraError, setCameraError] = useState(null);

  const stateRef = useRef(PresenceState.NO_PERSON);
  const presentStreakRef = useRef(0);
  const absentStreakRef = useRef(0);

  const streamRef = useRef(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const pollTimerRef = useRef(null);
  const holdTimerRef = useRef(null);

  const setState = useCallback((next) => {
    stateRef.current = next;
    setPresenceState(next);
  }, []);

  const captureFrame = useCallback(() => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return Promise.resolve(null);
    if (!canvasRef.current) canvasRef.current = document.createElement('canvas');
    const canvas = canvasRef.current;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.7));
  }, []);

  const checkPresence = useCallback(async () => {
    const blob = await captureFrame();
    if (!blob) return;

    let present;
    try {
      const form = new FormData();
      form.append('frame', blob, 'frame.jpg');
      const result = await apiPostJSON('/api/vision/presence', form, true);
      present = !!result.person_present;
    } catch (err) {
      console.error('[presence] check failed:', err);
      return; // transient hiccup -- don't let a single failed request flip state
    }

    const current = stateRef.current;

    if (present) {
      absentStreakRef.current = 0;
      presentStreakRef.current += 1;

      // Only NO_PERSON reacts to a growing present-streak -- once we're past
      // that (PERSON_DETECTED or CONVERSATION_ACTIVE), continued presence is
      // a no-op here. THIS is what stops many consecutive "present" polls of
      // the same person from re-triggering PERSON_DETECTED over and over.
      if (current === PresenceState.NO_PERSON && presentStreakRef.current >= PRESENT_CONFIRM_STREAK) {
        setState(PresenceState.PERSON_DETECTED); // the single "person detected" event
        holdTimerRef.current = setTimeout(() => {
          if (stateRef.current === PresenceState.PERSON_DETECTED) {
            setState(PresenceState.CONVERSATION_ACTIVE); // hands off to the conversation module
          }
        }, DETECTED_HOLD_MS);
      }
    } else {
      presentStreakRef.current = 0;
      if (current === PresenceState.PERSON_DETECTED || current === PresenceState.CONVERSATION_ACTIVE) {
        absentStreakRef.current += 1;
        if (absentStreakRef.current >= ABSENT_CONFIRM_STREAK) {
          if (holdTimerRef.current) {
            clearTimeout(holdTimerRef.current);
            holdTimerRef.current = null;
          }
          absentStreakRef.current = 0;
          setState(PresenceState.NO_PERSON); // person left -- reset for the next one
        }
      }
    }
  }, [captureFrame, setState]);

  useEffect(() => {
    if (!enabled) return undefined;

    let cancelled = false;

    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const video = document.createElement('video');
        video.srcObject = stream;
        video.muted = true;
        video.playsInline = true;
        videoRef.current = video;
        return video.play().catch(() => {});
      })
      .then(() => {
        if (cancelled) return;
        checkPresence();
        pollTimerRef.current = setInterval(checkPresence, POLL_MS);
      })
      .catch((err) => {
        console.error('[presence] camera unavailable:', err);
        if (!cancelled) setCameraError(err.message || err.name || 'camera access failed');
      });

    return () => {
      cancelled = true;
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      videoRef.current = null;
      presentStreakRef.current = 0;
      absentStreakRef.current = 0;
      stateRef.current = PresenceState.NO_PERSON;
      setPresenceState(PresenceState.NO_PERSON);
    };
  }, [enabled, checkPresence]);

  return { presenceState, cameraError };
}
