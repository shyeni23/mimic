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
  const [state, setState] = useState('idle');   // idle | working | done | error
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
    c.getContext('2d').drawImage(video, 0, 0);
    return new Promise((resolve) => c.toBlob(resolve, 'image/jpeg', 0.92));
  };

  const run = async () => {
    setState('working');
    setMessage('');
    try {
      const blob = await capture();
      if (!blob) throw new Error("couldn't capture the camera");
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
        onClick={run}
        disabled={state === 'working'}
      >
        <RiSparklingLine />
        {state === 'working' ? `Creating your look… ${elapsed}s` : 'See it properly on me'}
      </button>

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
