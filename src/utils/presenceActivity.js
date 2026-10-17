/**
 * "The customer is still here" signal, shared between the conversation and
 * the presence camera.
 *
 * Presence is judged purely on whether MediaPipe can see a full-body pose.
 * That fails constantly for ordinary reasons -- leaning in to speak, turning
 * to look at the screen, stepping half out of frame -- and after a few failed
 * polls the mirror decided the customer had left, started a NEW session and
 * wiped the conversation. Confirmed in use: reply, then the chat restarts.
 *
 * Someone who is talking to Aria is obviously still standing there, whatever
 * the camera can see. The conversation marks activity here, and the presence
 * hook refuses to declare absence while that activity is recent.
 */
let lastActivityAt = 0;

/** Call whenever the customer speaks/types, or Aria replies. */
export function markConversationActivity() {
  lastActivityAt = Date.now();
}

/** True if the conversation has been active within `windowMs`. */
export function isConversationActive(windowMs = 45000) {
  return Date.now() - lastActivityAt < windowMs;
}

export function resetConversationActivity() {
  lastActivityAt = 0;
}

/**
 * Presence polling pauses while the try-on mirror is live.
 *
 * Both run MediaPipe Pose: presence sends a frame to the backend every 1.5s
 * (server-side inference), try-on runs it in the browser. On a CPU-only
 * laptop they fight for the same cores -- try-on's first inference measured
 * ~12s in isolation but sat on "Getting the mirror ready..." past a minute
 * with presence also running. The customer is plainly present while using
 * the mirror, so polling for them is wasted work anyway.
 */
let presenceSuspended = false;
export const suspendPresence = () => { presenceSuspended = true; };
export const resumePresence = () => { presenceSuspended = false; };
export const isPresenceSuspended = () => presenceSuspended;
