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
