/* eslint-disable react-hooks/exhaustive-deps */
import { useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '../../utils/api';
import { suspendPresence, resumePresence } from '../../utils/presenceActivity';

const LIGHTING = {
  natural: 'transparent',
  studio: 'rgba(255, 255, 255, 0.08)',
  warm: 'rgba(255, 180, 80, 0.10)',
  cool: 'rgba(100, 180, 255, 0.10)',
};
// PINNED, deliberately. The unversioned "@mediapipe/pose" path resolves to
// whatever is newest, and a newer build ships an asset loader that throws
// "Cannot read properties of undefined (reading '...pose_solution_packed_
// assets.data')" from xhr.onprogress -- confirmed live on a clean machine.
// Do not drop the version without testing the overlay end to end.
const MEDIAPIPE_CDN = 'https://cdn.jsdelivr.net/npm/@mediapipe/pose@0.5.1675469404';
// Pose inference on a CPU laptop costs ~60-90ms a frame. Asking for 60fps
// queues work faster than it completes, each send holding its own buffers,
// until the tab exhausts memory ("could not allocate additional memory").
// Target a rate the hardware can actually sustain, and never have more than
// one inference in flight.
const TARGET_FPS = 12;
const FRAME_INTERVAL_MS = 1000 / TARGET_FPS;
const MAX_CONSECUTIVE_FAILURES = 5;
// A single inference that never settles. pose.send() REJECTING was handled;
// hanging was not -- inFlightRef stayed true, the loop did nothing further,
// the failure counter never advanced, and the mirror sat on "Getting the
// mirror ready..." indefinitely. Observed live for over a minute.
const SEND_TIMEOUT_MS = 20000;
// The whole warm-up: model download plus first inference. Past this,
// something is wrong that waiting will not fix (slow or blocked CDN).
const WARMUP_TIMEOUT_MS = 45000;

// MediaPipe Pose landmark indices (same ones body_shape.py uses).
const L_SHOULDER = 11;
const R_SHOULDER = 12;
const L_HIP = 23;
const R_HIP = 24;
// Garment image is sized relative to shoulder width (clothing patterns look
// right at ~1.6x the shoulder span) and anchored by its vertical placement.
// maxHeightMul caps the rendered height against TORSO length. Scaling by
// width alone lets the image's own aspect ratio decide the height: a 3:4
// product photo at shoulder width renders ~1.7x the torso, so a shirt ran
// 75px past the hips and reached mid-thigh. The cap keeps each garment
// inside a plausible envelope for what it actually is.
const GARMENT_LAYOUT = {
  top: { widthMul: 1.6, topOffset: 0.3, hAlign: 'shoulders', maxHeightMul: 1.35 },
  dress: { widthMul: 1.5, topOffset: 0.2, hAlign: 'shoulders', maxHeightMul: 2.3 },
  bottom: { widthMul: 1.3, topOffset: 0.0, hAlign: 'hips', maxHeightMul: 2.0 },
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
  const inFlightRef = useRef(false);     // one inference at a time (back-pressure)
  const lastFrameAtRef = useRef(0);      // rate limit to TARGET_FPS
  const failuresRef = useRef(0);         // consecutive send() rejections
  const stoppedRef = useRef(false);      // hard stop after repeated failures
  const statusRef = useRef('loading');   // read inside onPoseResults (not reactive)
  const warmupTimerRef = useRef(null);
  const streamRef = useRef(null);
  const [status, setStatus] = useState('loading');  // loading | ready | error
  const [errorMessage, setErrorMessage] = useState('');
  // Catalog photo with its white studio background stripped (see
  // removeWhiteBackground) -- falls back to the original URL on failure.
  const [cutoutUrl, setCutoutUrl] = useState(null);
  // What the customer needs to change about how they're standing. The
  // overlay used to just fade to 30% and say nothing, which reads as "it's
  // broken" rather than "step back".
  const [guidance, setGuidance] = useState(null);
  const guidanceRef = useRef(null);

  useEffect(() => {
    let stale = false;
    if (!item?.image_url) { setCutoutUrl(null); return undefined; }
    setCutoutUrl(item.image_url);                   // show something immediately
    (async () => {
      // Prefer the SERVER cutout: GrabCut segments properly, follows sleeves
      // and hems, and survives a white garment on a white backdrop -- the
      // browser flood-fill below erased those entirely (96% of pixels).
      if (item.id) {
        const serverCutout = `${API_BASE_URL}/api/inventory/${item.id}/cutout`;
        try {
          const res = await fetch(serverCutout, { method: 'HEAD' });
          if (res.ok) { if (!stale) setCutoutUrl(serverCutout); return; }
        } catch { /* fall through to the browser version */ }
      }
      const url = await removeWhiteBackground(item.image_url);
      if (!stale) setCutoutUrl(url);
    })();
    return () => { stale = true; };
  }, [item?.image_url, item?.id]);

  // ---------- Camera + MediaPipe boot
  useEffect(() => {
    let cancelled = false;
    // Free the CPU for pose inference -- see presenceActivity.suspendPresence.
    suspendPresence();
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
          await loadScript(`${MEDIAPIPE_CDN}/pose.js`);
        }
        if (cancelled) return;
        const pose = new window.Pose({
          locateFile: (f) => `${MEDIAPIPE_CDN}/${f}`,
        });
        pose.setOptions({
          modelComplexity: 1, smoothLandmarks: true, enableSegmentation: false,
          minDetectionConfidence: 0.5, minTrackingConfidence: 0.5,
        });
        pose.onResults(onPoseResults);
        poseRef.current = pose;
        // NOT 'ready' yet: the first inference downloads and initialises the
        // wasm model, measured at ~13s on this hardware. Saying ready here
        // left the customer staring at a bare camera with no explanation.
        statusRef.current = 'warming';
        setStatus('warming');
        onPoseReady?.();
        // Watchdog: the model is fetched from a CDN on first use, and a slow
        // or blocked network leaves no other signal that anything is wrong.
        warmupTimerRef.current = setTimeout(() => {
          if (statusRef.current === 'warming') {
            stoppedRef.current = true;
            statusRef.current = 'error';
            setErrorMessage('The body-tracking model is taking too long to load. '
              + 'Check the internet connection and reload the page.');
            setStatus('error');
          }
        }, WARMUP_TIMEOUT_MS);
        loop();
      } catch (err) {
        if (cancelled) return;
        const msg = err?.name === 'NotAllowedError'
          ? 'Camera access was denied. Allow it in your browser to use try-on.'
          : `Try-on couldn't start: ${err.message || err}`;
        setErrorMessage(msg);
        statusRef.current = 'error';
        setStatus('error');
        onError?.(err);
      }
    })();
    return () => {
      cancelled = true;
      // The loop is async: an in-flight send() resolves AFTER unmount and
      // would queue another frame against a closed Pose. This flag is what
      // actually stops it; cancelAnimationFrame alone cannot.
      stoppedRef.current = true;
      resumePresence();
      if (warmupTimerRef.current) clearTimeout(warmupTimerRef.current);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      try { poseRef.current?.close(); } catch { /* MediaPipe closed */ }
    };
  }, []);

  // ---------- Per-frame: push the current video frame into MediaPipe.
  // Back-pressured and rate-limited. The first version fired send() on every
  // animation frame and swallowed the rejection, so on a CPU laptop the
  // inferences piled up and a failing load retried ~60x a second until the
  // tab ran out of memory and Windows killed the process.
  const loop = async () => {
    if (stoppedRef.current) return;
    const pose = poseRef.current;
    const video = videoRef.current;
    const now = performance.now();

    if (pose && video && video.readyState >= 2
        && !inFlightRef.current                                   // one at a time
        && now - lastFrameAtRef.current >= FRAME_INTERVAL_MS) {    // and not too often
      inFlightRef.current = true;
      lastFrameAtRef.current = now;
      try {
        // Timed: a hung send would otherwise block the loop forever.
        let timer;
        await Promise.race([
          pose.send({ image: video }),
          new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error(`pose.send timed out after ${SEND_TIMEOUT_MS}ms`)),
                               SEND_TIMEOUT_MS);
          }),
        ]).finally(() => clearTimeout(timer));
        failuresRef.current = 0;
      } catch (err) {
        failuresRef.current += 1;
        if (failuresRef.current >= MAX_CONSECUTIVE_FAILURES) {
          stoppedRef.current = true;
          console.error('[try-on] pose tracking failed repeatedly, stopping:', err);
          setErrorMessage('Pose tracking could not start. The camera still works -- reload to try again.');
          statusRef.current = 'error';
        setStatus('error');
          return;                                                  // stop the loop for good
        }
      } finally {
        inFlightRef.current = false;
      }
    }
    if (!stoppedRef.current) rafRef.current = requestAnimationFrame(loop);
  };

  // ---------- Landmarks -> overlay position
  const onPoseResults = (res) => {
    // First results back == the model is live. Clear the warming message.
    // Only promote OUT OF warming -- a late result must never overwrite a
    // real error and hide it from the customer.
    if (statusRef.current === 'warming') {
      statusRef.current = 'ready';
      setStatus('ready');
      if (warmupTimerRef.current) { clearTimeout(warmupTimerRef.current); warmupTimerRef.current = null; }
    }
    const overlay = overlayRef.current;
    const video = videoRef.current;
    if (!overlay || !video) return;
    const marks = res?.poseLandmarks;
    const layout = GARMENT_LAYOUT[item?.category];
    // Say it once, not on every frame -- setState at 12fps would rerender
    // the whole mirror continuously.
    const say = (msg) => {
      if (guidanceRef.current !== msg) { guidanceRef.current = msg; setGuidance(msg); }
    };

    if (!marks) { overlay.style.opacity = '0'; say('Step in front of the mirror so I can see you.'); return; }
    if (!layout || !item?.image_url) { overlay.style.opacity = '0'; say(null); return; }

    const ls = marks[L_SHOULDER];
    const rs = marks[R_SHOULDER];
    const lh = marks[L_HIP];
    const rh = marks[R_HIP];
    // All four points must be clearly visible; otherwise the overlay drifts.
    const shoulderVis = Math.min(ls?.visibility ?? 0, rs?.visibility ?? 0);
    const hipVis = Math.min(lh?.visibility ?? 0, rh?.visibility ?? 0);
    if (Math.min(shoulderVis, hipVis) < 0.4) {
      overlay.style.opacity = '0.3';
      // Name the ACTUAL problem: hips missing almost always means standing
      // too close, which is the most common way customers get this wrong.
      say(hipVis < 0.4 && shoulderVis >= 0.4
        ? 'Step back a little so I can see down to your hips.'
        : 'Face the mirror so I can see your shoulders and hips.');
      return;
    }

    const w = video.clientWidth || video.videoWidth;
    const h = video.clientHeight || video.videoHeight;
    const toPx = (p) => ({ x: (flipped ? 1 - p.x : p.x) * w, y: p.y * h });
    const lsP = toPx(ls); const rsP = toPx(rs);
    const lhP = toPx(lh); const rhP = toPx(rh);

    const shoulderMid = { x: (lsP.x + rsP.x) / 2, y: (lsP.y + rsP.y) / 2 };
    const hipMid = { x: (lhP.x + rhP.x) / 2, y: (lhP.y + rhP.y) / 2 };
    const shoulderSpan = Math.hypot(rsP.x - lsP.x, rsP.y - lsP.y);
    const torsoLen = Math.hypot(hipMid.x - shoulderMid.x, hipMid.y - shoulderMid.y);

    let width = Math.max(80, shoulderSpan * layout.widthMul);
    // Height follows the image's own aspect ratio once width is set, so cap
    // it against the body and scale the whole garment down if it overshoots
    // -- narrower than the shoulders is better than a shirt down to the knee.
    const aspect = (overlay.naturalHeight || 4) / (overlay.naturalWidth || 3);
    const maxHeight = torsoLen * layout.maxHeightMul;
    if (width * aspect > maxHeight) width = maxHeight / aspect;

    const anchor = layout.hAlign === 'hips' ? hipMid : shoulderMid;
    const topY = anchor.y - torsoLen * layout.topOffset;
    const angleDeg = Math.atan2(rsP.y - lsP.y, rsP.x - lsP.x) * 180 / Math.PI;

    overlay.style.width = `${width}px`;
    overlay.style.left = `${anchor.x - width / 2}px`;
    overlay.style.top = `${topY}px`;
    overlay.style.transform = `rotate(${angleDeg}deg)`;
    overlay.style.opacity = '0.92';
    say(null);                       // positioned correctly -- nothing to say
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
      {status === 'ready' && guidance && <div className="tryon-guidance">{guidance}</div>}
      {status === 'loading' && <div className="tryon-overlay-msg">Starting the camera…</div>}
      {status === 'warming' && (
        <div className="tryon-overlay-msg">
          Getting the mirror ready…
          <br />
          <small>First use downloads the body-tracking model. This takes a few seconds.</small>
        </div>
      )}
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
