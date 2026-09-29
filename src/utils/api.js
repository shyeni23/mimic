const API_BASE_URL =
  process.env.REACT_APP_API_BASE_URL || 'http://localhost:8000';

// A page's very first cross-origin request to the backend (typically one of
// several fired simultaneously right at mount -- category/occasion lookups,
// the initial session POST, etc.) can hit a cold-connection hiccup and fail
// at the network level (fetch() itself throws, e.g. "Failed to fetch")
// before any response ever comes back -- confirmed live, reproducibly, on
// this dev setup: the first request after a fresh page load fails every
// time, and every request after it succeeds instantly. That's a transport-
// level hiccup, not an HTTP error, so retrying once (same pattern the
// backend's own scripts already use for flaky Supabase calls) fixes it
// silently instead of a filter row being permanently stuck on "All" for the
// rest of that page's lifetime.
async function fetchWithRetry(url, opts, tries = 4) {
  let lastErr;
  for (let i = 0; i < tries; i++) {
    try {
      return await fetch(url, opts);
    } catch (err) {
      lastErr = err;
      // Backing off (not a fixed 200ms) matters here: at page mount, several
      // requests fire in the same tick (session POST, category/occasion
      // lookups, the product list...) and confirmed live, a fixed short
      // delay wasn't enough to outlast whatever's congested at that exact
      // moment -- both retries still failed. Same increasing-delay shape the
      // backend's own scripts already use for flaky Supabase calls.
      if (i < tries - 1) await new Promise((r) => setTimeout(r, 300 * (i + 1)));
    }
  }
  throw lastErr;
}

// FastAPI errors arrive as {"detail": "..."}; surface the message itself, not
// the raw JSON -- the body scanner shows err.message directly on screen.
async function readErrorDetail(res) {
  const text = await res.text().catch(() => '');
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed?.detail === 'string') return parsed.detail;
    if (Array.isArray(parsed?.detail)) return parsed.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
  } catch { /* not JSON */ }
  return text || res.statusText || `Request failed (${res.status})`;
}

export async function apiPost(path, body, isFormData = false) {
  const opts = { method: 'POST' };
  if (isFormData) {
    opts.body = body;
  } else {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const res = await fetchWithRetry(`${API_BASE_URL}${path}`, opts);
  if (!res.ok) {
    throw new Error(await readErrorDetail(res));
  }
  return res;
}

export async function apiPostJSON(path, body, isFormData = false) {
  const res = await apiPost(path, body, isFormData);
  return res.json();
}

export async function apiGet(path) {
  const res = await fetchWithRetry(`${API_BASE_URL}${path}`);
  if (!res.ok) {
    throw new Error(await readErrorDetail(res));
  }
  return res;
}

export async function apiGetJSON(path) {
  const res = await apiGet(path);
  return res.json();
}

export { API_BASE_URL };
