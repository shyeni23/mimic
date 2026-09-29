/**
 * Interaction event logger (Module 3, implicit-feedback pipeline).
 *
 * Every implicit signal the customer generates -- card impressions, clicks,
 * tryon requests, add-to-cart, skips -- posts to /api/events for future
 * training data for the DL recommender's user tower. We can't train a
 * two-tower model without interaction logs, and we can't collect them without
 * shipping this. Data starts accumulating from day one; the model comes later.
 *
 * Batching: impressions and scrolls debounce into a single POST every 500ms
 * so a 20-card grid doesn't spam 20 requests. Eager events (add_to_cart,
 * tryon) bypass the queue and post immediately.
 */
import { useEffect, useRef } from 'react';
import { apiPostJSON } from '../utils/api';

const buffer = [];
let flushTimer = null;

function scheduleFlush() {
  if (flushTimer) return;
  flushTimer = setTimeout(async () => {
    const batch = buffer.splice(0);
    flushTimer = null;
    if (!batch.length) return;
    try {
      await apiPostJSON('/api/events/batch', batch);
    } catch {
      // Best-effort -- interaction logs shouldn't ever break a page.
    }
  }, 500);
}

/**
 * Queue an event for the next batch flush. Use for impressions, scrolls,
 * dismissals -- anything where 500ms of latency is fine.
 */
export function logEvent(sessionId, itemId, eventType, context = {}) {
  if (!sessionId) return;
  buffer.push({
    session_id: sessionId,
    item_id: itemId || null,
    event_type: eventType,
    context,
  });
  scheduleFlush();
}

/**
 * Post an event immediately, no batching. Use for high-value signals
 * (add_to_cart, tryon) where losing a batch mid-flush would matter.
 */
export function logEventNow(sessionId, itemId, eventType, context = {}) {
  if (!sessionId) return;
  apiPostJSON('/api/events', {
    session_id: sessionId,
    item_id: itemId || null,
    event_type: eventType,
    context,
  }).catch(() => {
    // Best-effort -- see above.
  });
}

/**
 * Hook: fire a single `view` event the first time an item card is at least
 * 50% visible in the viewport. Won't refire on re-scroll or re-mount.
 *
 *   const cardRef = useRef(null);
 *   useImpressionLogger(sessionId, item.id, cardRef);
 *   return <div ref={cardRef}>...</div>;
 */
export function useImpressionLogger(sessionId, itemId, elementRef) {
  const seen = useRef(false);
  useEffect(() => {
    if (!elementRef?.current || seen.current || !sessionId || !itemId) return;
    const node = elementRef.current;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !seen.current) {
          seen.current = true;
          logEvent(sessionId, itemId, 'view');
          io.disconnect();
        }
      },
      { threshold: 0.5 },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [sessionId, itemId, elementRef]);
}
