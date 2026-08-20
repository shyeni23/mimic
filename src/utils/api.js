const API_BASE_URL =
  process.env.REACT_APP_API_BASE_URL || 'http://localhost:8000';

export async function apiPost(path, body, isFormData = false) {
  const opts = { method: 'POST' };
  if (isFormData) {
    opts.body = body;
  } else {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE_URL}${path}`, opts);
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(detail);
  }
  return res;
}

export async function apiPostJSON(path, body, isFormData = false) {
  const res = await apiPost(path, body, isFormData);
  return res.json();
}

export { API_BASE_URL };
