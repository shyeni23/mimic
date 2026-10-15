/* eslint-disable react-hooks/exhaustive-deps */
import { useEffect, useRef, useState } from 'react';

const LIGHTING = {
  natural: 'transparent',
  studio: 'rgba(255, 255, 255, 0.08)',
  warm: 'rgba(255, 180, 80, 0.10)',
  cool: 'rgba(100, 180, 255, 0.10)',
};
// MediaPipe Pose landmark indices (same ones body_shape.py uses).
const L_SHOULDER = 11;
const R_SHOULDER = 12;
const L_HIP = 23;
const R_HIP = 24;
// Garment image is sized relative to shoulder width (clothing patterns look
// right at ~1.6x the shoulder span) and anchored by its vertical placement.
const GARMENT_LAYOUT = {
  top: { widthMul: 1.6, topOffset: 0.3, hAlign: 'shoulders' },
  dress: { widthMul: 1.5, topOffset: 0.2, hAlign: 'shoulders' },
  bottom: { widthMul: 1.3, topOffset: 0.0, hAlign: 'hips' },
  // Accessories don't try on; the component shows them as a side chip.
};


/**
 * Live camera + pose-tracked garment overlay. Loads MediaPipe Pose on first
 * mount (~2s one-off), draws every frame to a hidden canvas, and positions
 * `item.image_url` over the person based on their shoulders/hips.
 *
 *   <TryOnMirror item={{image_url, category, name}} lighting="warm" zoom={1}
 *                flipped={false} onPoseReady={...} />
 */
export default function TryOnMirror({ item, lighting = 'natural', zoom = 1, flipped = false,
                                     onPoseReady, onError }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const overlayRef = useRef(null);
  const poseRef = useRef(null);
  const rafRef = useRef(null);
  const streamRef = useRef(null);
  const [status, setStatus] = useState('loading');  // loading | ready | error
  const [errorMessage, setErrorMessage] = useState('');
  // Catalog photo with its white studio background stripped (see
  // removeWhiteBackground) -- falls back to the original URL on failure.
  const [cutoutUrl, setCutoutUrl] = useState(null);

  useEffect(() => {
    let stale = false;
    if (!item?.image_url) { setCutoutUrl(null); return undefined; }
    setCutoutUrl(item.image_url);                   // show something immediately
    removeWhiteBackground(item.image_url).then((url) => { if (!stale) setCutoutUrl(url); });
    return () => { stale = true; };
  }, [item?.image_url]);

  // ---------- Camera + MediaPipe boot
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: 960, height: 720 }, audio: false,
        });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        const video = videoRef.current;
        video.srcObject = stream;
        await video.play();

        // MediaPipe Pose from the official CDN build. Deliberately NOT bundled
        // (its wasm + model are ~5MB) -- loaded once per session on this page.
        if (!window.Pose) {
          await loadScript('https://cdn.jsdelivr.net/npm/@mediapipe/pose/pose.js');
        }
        if (cancelled) return;
        const pose = new window.Pose({
          locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/pose/${f}`,
        });
        pose.setOptions({
          modelComplexity: 1, smoothLandmarks: true, enableSegmentation: false,
          minDetectionConfidence: 0.5, minTrackingConfidence: 0.5,
        });
        pose.onResults(onPoseResults);
        poseRef.current = pose;
        setStatus('ready');
        onPoseReady?.();
        loop();
      } catch (err) {
        if (cancelled) return;
        const msg = err?.name === 'NotAllowedError'
          ? 'Camera access was denied. Allow it in your browser to use try-on.'
          : `Try-on couldn't start: ${err.message || err}`;
        setErrorMessage(msg);
        setStatus('error');
        onError?.(err);
      }
    })();
    return () => {
      cancelled = true;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      try { poseRef.current?.close(); } catch { /* MediaPipe closed */ }
    };
  }, []);

  // ---------- Per-frame: push the current video frame into MediaPipe
  const loop = () => {
    const pose = poseRef.current;
    const video = videoRef.current;
    if (!pose || !video || video.readyState < 2) {
      rafRef.current = requestAnimationFrame(loop);
      return;
    }
    pose.send({ image: video }).catch(() => { /* occasional dropped frame */ });
    rafRef.current = requestAnimationFrame(loop);
  };

  // ---------- Landmarks -> overlay position
  const onPoseResults = (res) => {
    const overlay = overlayRef.current;
    const video = videoRef.current;
    if (!overlay || !video) return;
    const marks = res?.poseLandmarks;
    const layout = GARMENT_LAYOUT[item?.category];
    if (!marks || !layout || !item?.image_url) { overlay.style.opacity = '0'; return; }

    const ls = marks[L_SHOULDER];
    const rs = marks[R_SHOULDER];
    const lh = marks[L_HIP];
    const rh = marks[R_HIP];
    // All four points must be clearly visible; otherwise the overlay drifts.
    const minVis = Math.min(ls?.visibility ?? 0, rs?.visibility ?? 0,
                            lh?.visibility ?? 0, rh?.visibility ?? 0);
    if (minVis < 0.4) { overlay.style.opacity = '0.3'; return; }

    const w = video.clientWidth || video.videoWidth;
    const h = video.clientHeight || video.videoHeight;
    const toPx = (p) => ({ x: (flipped ? 1 - p.x : p.x) * w, y: p.y * h });
    const lsP = toPx(ls); const rsP = toPx(rs);
    const lhP = toPx(lh); const rhP = toPx(rh);

    const shoulderMid = { x: (lsP.x + rsP.x) / 2, y: (lsP.y + rsP.y) / 2 };
    const hipMid = { x: (lhP.x + rhP.x) / 2, y: (lhP.y + rhP.y) / 2 };
    const shoulderSpan = Math.hypot(rsP.x - lsP.x, rsP.y - lsP.y);
    const torsoLen = Math.hypot(hipMid.x - shoulderMid.x, hipMid.y - shoulderMid.y);

    const width = Math.max(80, shoulderSpan * layout.widthMul);
    const anchor = layout.hAlign === 'hips' ? hipMid : shoulderMid;
    const topY = anchor.y - torsoLen * layout.topOffset;
    const angleDeg = Math.atan2(rsP.y - lsP.y, rsP.x - lsP.x) * 180 / Math.PI;

    overlay.style.width = `${width}px`;
    overlay.style.left = `${anchor.x - width / 2}px`;
    overlay.style.top = `${topY}px`;
    overlay.style.transform = `rotate(${angleDeg}deg)`;
    overlay.style.opacity = '0.92';
  };

  return (
    <div className="tryon-mirror" style={{ background: LIGHTING[lighting] }}>
      <video
        ref={videoRef}
        playsInline
        muted
        style={{
          width: '100%', height: '100%', objectFit: 'cover', display: 'block',
          transform: `scale(${zoom})${flipped ? ' scaleX(-1)' : ''}`,
          transformOrigin: 'center',
        }}
      />
      <canvas ref={canvasRef} style={{ display: 'none' }} />
      {item?.image_url && (
        <img
          ref={overlayRef}
          src={cutoutUrl || item.image_url}
          alt={item.name || 'try-on'}
          className="tryon-garment"
          style={{
            position: 'absolute', pointerEvents: 'none', opacity: 0,
            transformOrigin: 'center top',
            transition: 'left .08s linear, top .08s linear, width .08s linear',
          }}
        />
      )}
      {status === 'loading' && <div className="tryon-overlay-msg">Loading pose tracking…</div>}
      {status === 'error' && <div className="tryon-overlay-msg tryon-error">{errorMessage}</div>}
    </div>
  );
}


/**
 * Catalog photos are shot on white. Pasting one straight onto a camera feed
 * looks like a sticker, so strip the background before overlaying.
 *
 * Flood-fills inward from the four edges, clearing any pixel close to the
 * corner colour and stopping at the garment's own edge. Edge-seeded rather
 * than "clear every white pixel", because a white kurta would otherwise
 * become a hole. Returns a transparent-PNG data URL, or the original on any
 * failure (CORS-tainted canvas, non-white background) -- the overlay still
 * works, it just keeps its backdrop.
 */
function removeWhiteBackground(url, tolerance = 32) {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    // Cache-buster, NOT for freshness: the product grid loads these same
    // images WITHOUT crossOrigin, so the browser caches a response carrying
    // no CORS headers. Re-requesting with crossOrigin then reuses that
    // poisoned entry and the load fails -- confirmed live, which would have
    // made background removal silently never run. A distinct URL gets its
    // own cache entry, fetched with the CORS headers intact.
    img.onerror = () => resolve(url);
    img.onload = () => {
      try {
        const { width: w, height: h } = img;
        const c = document.createElement('canvas');
        c.width = w; c.height = h;
        const ctx = c.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(img, 0, 0);
        const data = ctx.getImageData(0, 0, w, h);
        const px = data.data;

        // Background colour = average of the four corners.
        const corners = [0, (w - 1) * 4, (h - 1) * w * 4, ((h - 1) * w + w - 1) * 4];
        const bg = [0, 1, 2].map((ch) =>
          Math.round(corners.reduce((sum, o) => sum + px[o + ch], 0) / corners.length));
        // Only strip if the border really is a flat light backdrop.
        if (bg[0] < 200 || bg[1] < 200 || bg[2] < 200) { resolve(url); return; }

        const visited = new Uint8Array(w * h);
        const stack = [];
        for (let x = 0; x < w; x++) { stack.push(x, x + (h - 1) * w); }
        for (let y = 0; y < h; y++) { stack.push(y * w, y * w + w - 1); }

        let cleared = 0;
        while (stack.length) {
          const idx = stack.pop();
          if (idx < 0 || idx >= w * h || visited[idx]) continue;
          const o = idx * 4;
          const dist = Math.abs(px[o] - bg[0]) + Math.abs(px[o + 1] - bg[1]) + Math.abs(px[o + 2] - bg[2]);
          if (dist > tolerance * 3) continue;      // hit the garment edge
          visited[idx] = 1;
          px[o + 3] = 0;                            // transparent
          cleared++;
          const x = idx % w;
          if (x > 0) stack.push(idx - 1);
          if (x < w - 1) stack.push(idx + 1);
          stack.push(idx - w, idx + w);
        }

        // A white garment on a white backdrop (white kurtas, cream sarees --
        // common in ethnic wear) has no edge for the fill to stop at, so it
        // leaks through and erases the product: a white t-shirt measured 96%
        // cleared. Anything past this threshold means the garment itself went
        // with it, so keep the original rather than overlay nothing.
        if (cleared / (w * h) > 0.85) { resolve(url); return; }

        ctx.putImageData(data, 0, 0);
        resolve(c.toDataURL('image/png'));
      } catch {
        resolve(url);                               // tainted canvas etc.
      }
    };
    img.src = url + (url.includes('?') ? '&' : '?') + 'cors=1';
  });
}


function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.async = true;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(s);
  });
}
