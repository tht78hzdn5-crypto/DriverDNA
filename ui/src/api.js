// Every figure the UI shows comes from these endpoints verbatim (UI-SPEC
// decision 2): the SPA formats for layout, it never computes a measurement.
export async function get(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} on ${path}`);
  }
  return response.json();
}

// Writes only ever wrap the engine's audited paths (UI-SPEC decision 3): the
// API layer holds no logic, so the UI is just forwarding intent.
export async function send(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `${response.status} on ${path}`);
  }
  return response.json();
}
