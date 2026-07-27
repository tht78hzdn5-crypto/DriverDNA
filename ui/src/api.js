// A session expired or was never established. Raised as an ordinary Error so
// existing `catch` blocks are unchanged, but carrying `status` so the shell
// can tell "you are signed out" apart from "that request failed".
//
// No `credentials:` option appears anywhere in this file, deliberately: every
// path below is relative, so every request is same-origin, and fetch already
// sends same-origin cookies by default. The session rides in an HttpOnly
// cookie the page cannot read — there is no token in JS to attach by hand.
export const UNAUTHENTICATED = "unauthenticated";

async function fail(response, path) {
  const body = await response.json().catch(() => ({}));
  const error = new Error(body.detail || `${response.status} on ${path}`);
  error.status = response.status;
  if (response.status === 401) {
    error.kind = UNAUTHENTICATED;
    // Broadcast rather than thread a callback through every view: any 401,
    // from any call site, drops the whole shell back to the sign-in gate.
    window.dispatchEvent(new CustomEvent("driverdna:unauthenticated"));
  }
  return error;
}

// Every figure the UI shows comes from these endpoints verbatim (UI-SPEC
// decision 2): the SPA formats for layout, it never computes a measurement.
export async function get(path) {
  const response = await fetch(path);
  if (!response.ok) throw await fail(response, path);
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
  if (!response.ok) throw await fail(response, path);
  return response.json();
}

// Upload (UI-SPEC decision 3, view 7): a multipart wrapper over
// `import_lap_file`, same audited path `driverdna import` uses per file —
// no Content-Type set here so the browser attaches its own multipart
// boundary, which fetch(JSON.stringify(...)) above would break.
export async function uploadLaps(formData) {
  const response = await fetch("/api/laps/upload", { method: "POST", body: formData });
  if (!response.ok) throw await fail(response, "upload");
  return response.json();
}

// Chat (UI-SPEC decision 4): no native EventSource here (it's GET-only, and
// this is a POST with a body) — read the SSE-framed response body directly.
// Each frame is a whole progress/response/error event, never partial text;
// `onEvent` fires once per frame, in order.
export async function streamChat(sessionId, text, onEvent) {
  const response = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) throw await fail(response, "chat message");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop(); // last (possibly incomplete) frame stays buffered
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice("data: ".length)));
    }
  }
}
