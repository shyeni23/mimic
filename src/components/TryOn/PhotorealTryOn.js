/**
 * "See it properly on me" -- photorealistic try-on.
 *
 * The live overlay next to this is a tracked cut-out: instant, free, honest
 * about colour and proportion, but flat. It cannot drape or fold. This
 * captures one frame and sends it to a diffusion try-on model, which
 * generates the customer actually wearing the garment -- real folds,
 * shadows and fit. That costs a GPU inference, so it is a photo, not a
 * live mirror; every commercial try-on works this way for the same reason.
 *
 * Hidden entirely when the backend reports the feature unconfigured, so a
 * mirror without a Replicate token simply doesn't offer it.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { RiSparklingLine, RiCloseLine, RiRefreshLine } from 'react-icons/ri';
import { API_BASE_URL } from '../../utils/api';
import './PhotorealTryOn.css';

function PhotorealTryOn({ item, videoEl, sessionId, onTryonStart, onTryonResult }, ref) {
  const [available, setAvailable] = useState(false);
  const [state, setState] = useState('idle');   // idle | counting | working | done | error
  const [count, setCount] = useState(0);
  const [resultUrl, setResultUrl] = useState(null);
  const [message, setMessage] = useState('');
  const elapsedRef = useRef(null);
  const [elapsed, setElapsed] = useState(0);
  // Pending auto-start timer. The mirror is touchless, so pressing a shutter
  // isn't an option for most customers -- the try-on fires on its own when a
  // garment is chosen. Held in a ref so a manual press (or a new garment)
  // can cancel a still-pending auto-start.
  const autoTimerRef = useRef(null);

  useEffect(() => {
    let stale = false;
    fetch(`${API_BASE_URL}/api/tryon/available`)
      .then((r) => r.json())
      .then((d) => { if (!stale) setAvailable(!!d.available); })
      .catch(() => { /* feature stays hidden */ });
    return () => { stale = true; };
  }, []);

  // A visible counter, because 10-20s of nothing reads as "it's broken".
  useEffect(() => {
    if (state !== 'working') { clearInterval(elapsedRef.current); return undefined; }
    setElapsed(0);
    elapsedRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(elapsedRef.current);
  }, [state]);

  const capture = () => {
    const video = videoEl?.current;
    if (!video || !video.videoWidth) return null;
    const c = document.createElement('canvas');
    c.width = video.videoWidth;
    c.height = video.videoHeight;
    const ctx = c.getContext('2d');
    ctx.drawImage(video, 0, 0);
    // The generated result is only as good as this frame, and a dark one
    // produces a muddy, unconvincing try-on. Check before spending a
    // generation on it.
    const { data } = ctx.getImageData(0, 0, c.width, c.height);
    let sum = 0;
    for (let i = 0; i < data.length; i += 4 * 97) sum += (data[i] + data[i + 1] + data[i + 2]) / 3;
    const brightness = sum / (data.length / (4 * 97));
    return new Promise((resolve) => c.toBlob((b) => resolve({ blob: b, brightness }), 'image/jpeg', 0.92));
  };

  /** 3-2-1 so the customer can actually pose. Capturing on the tap caught
   *  them looking down at the button, and the input photo decides how good
   *  the generated result is. */
  const start = () => {
    // A manual press (or the auto-start firing) consumes any pending timer.
    if (autoTimerRef.current) { clearTimeout(autoTimerRef.current); autoTimerRef.current = null; }
    setState('counting');
    setMessage('');
    let n = 3;
    setCount(n);
    const tick = setInterval(() => {
      n -= 1;
      setCount(n);
      if (n <= 0) { clearInterval(tick); run(); }
    }, 1000);
  };

  const run = async () => {
    setState('working');
    setMessage('');
    try {
      const shot = await capture();
      if (!shot?.blob) throw new Error("couldn't capture the camera");
      if (shot.brightness < 55) {
        throw new Error('It\'s too dark for a good result — switch on more light and try again');
      }
      // Aria builds anticipation while the diffusion model runs (~30-60s).
      // Fired here, not at countdown, so a dark-frame bail-out above doesn't
      // leave her promising a reveal that never comes.
      onTryonStart?.(item);
      const blob = shot.blob;
      const form = new FormData();
      form.append('item_id', item.id);
      form.append('photo', blob, 'person.jpg');
      if (sessionId) form.append('session_id', sessionId);

      const res = await fetch(`${API_BASE_URL}/api/tryon/generate`, { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `failed (${res.status})`);
      setResultUrl(data.image_url);
      setState('done');
      // The result is now on screen -- Aria reacts to the finished look.
      onTryonResult?.(item);
    } catch (err) {
      setMessage(err.message || 'Try-on failed');
      setState('error');
    }
  };

  const ready = available && !!item?.id;
  // No dep array on purpose: start() closes over the current item, and the
  // garment changes without `ready` changing, so a memoized handle would
  // keep generating the previously selected item.
  useImperativeHandle(ref, () => ({ ready, state, start }));

  // Touchless auto-start: when a garment is selected, reset and fire the
  // try-on on its own after a short beat (so the customer registers the new
  // item before the 3-2-1 begins). Keyed on item.id -- re-runs for each new
  // garment, never loops on the same one. A manual press cancels the pending
  // timer (see start()). The generated result's "regenerate" button and the
  // live-mirror fallback both still work if the auto shot comes out poorly.
  useEffect(() => {
    if (!ready) return undefined;
    setState('idle');
    setResultUrl(null);
    setMessage('');
    // 2.5s lead + the 3-2-1 countdown = ~5.5s before the frame is actually
    // grabbed, which comfortably clears the mirror camera's warmup so the
    // auto shot isn't "couldn't capture the camera".
    if (autoTimerRef.current) clearTimeout(autoTimerRef.current);
    autoTimerRef.current = setTimeout(() => { autoTimerRef.current = null; start(); }, 2500);
    return () => {
      if (autoTimerRef.current) { clearTimeout(autoTimerRef.current); autoTimerRef.current = null; }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, item?.id]);

  if (!ready) return null;

  return (
    <>
      <button
        className="photoreal-btn"
        onClick={start}
        disabled={state === 'working' || state === 'counting'}
      >
        <RiSparklingLine />
        {state === 'counting' ? `Get ready… ${count}`
          : state === 'working' ? `Creating your look… ${elapsed}s`
            : 'See it properly on me'}
      </button>

      {/* Portaled straight onto <body>. These are meant to cover the WHOLE
          screen (position: fixed; inset: 0), but this component is nested
          inside the side panel's motion.div -- Framer Motion puts an inline
          transform on that div for its enter animation, and per the CSS
          spec ANY transform on an ancestor traps position:fixed descendants
          inside that ancestor's box instead of the viewport. Confirmed
          live: the result rendered as a small card clipped to the sidebar,
          with the item name wrapping word-by-word for lack of room. A
          portal is the standard fix -- it renders this subtree as a child
          of <body> in the DOM, outside any transformed ancestor, while
          staying part of the same React tree (events, context, state all
          still work normally). */}
      {state === 'counting' && createPortal(
        <div className="photoreal-countdown">
          <span>{count}</span>
          <p>Stand facing the mirror</p>
        </div>,
        document.body,
      )}

      {state === 'working' && createPortal(
        <div className="photoreal-countdown photoreal-generating">
          <p>Creating your look…</p>
          <small>About 15 seconds. You can move now.</small>
        </div>,
        document.body,
      )}

      {/* Over the mirror, not tucked into the side panel. A rejected frame
          used to report itself in a small panel message below the fold:
          the customer pressed the shutter, watched the countdown, and then
          saw nothing at all, which reads exactly like a dead button. */}
      {state === 'error' && createPortal(
        <div className="photoreal-countdown photoreal-failed" onClick={() => setState('idle')}>
          <p>{message}</p>
          <small>Tap to dismiss — the live mirror still works.</small>
        </div>,
        document.body,
      )}

      {state === 'done' && resultUrl && createPortal(
        <div className="photoreal-result" onClick={() => setState('idle')}>
          <img src={resultUrl} alt={`You wearing ${item.name}`} />
          <div className="photoreal-result-bar">
            <span>{item.name}</span>
            <button onClick={(e) => { e.stopPropagation(); run(); }} title="Generate again">
              <RiRefreshLine />
            </button>
            <button onClick={() => setState('idle')} title="Close">
              <RiCloseLine />
            </button>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}

export default forwardRef(PhotorealTryOn);
