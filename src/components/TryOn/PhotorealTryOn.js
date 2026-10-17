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
import { useEffect, useRef, useState } from 'react';
import { RiSparklingLine, RiCloseLine, RiRefreshLine } from 'react-icons/ri';
import { API_BASE_URL } from '../../utils/api';
import './PhotorealTryOn.css';

export default function PhotorealTryOn({ item, videoEl, sessionId }) {
  const [available, setAvailable] = useState(false);
  const [state, setState] = useState('idle');   // idle | counting | working | done | error
  const [count, setCount] = useState(0);
  const [resultUrl, setResultUrl] = useState(null);
  const [message, setMessage] = useState('');
  const elapsedRef = useRef(null);
  const [elapsed, setElapsed] = useState(0);

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
    } catch (err) {
      setMessage(err.message || 'Try-on failed');
      setState('error');
    }
  };

  if (!available || !item?.id) return null;

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

      {state === 'counting' && (
        <div className="photoreal-countdown">
          <span>{count}</span>
          <p>Stand facing the mirror</p>
        </div>
      )}

      {state === 'working' && (
        <div className="photoreal-countdown photoreal-generating">
          <p>Creating your look…</p>
          <small>About 15 seconds. You can move now.</small>
        </div>
      )}

      {state === 'error' && (
        <div className="photoreal-msg photoreal-error">
          {message} — the live mirror still works.
        </div>
      )}

      {state === 'done' && resultUrl && (
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
        </div>
      )}
    </>
  );
}
