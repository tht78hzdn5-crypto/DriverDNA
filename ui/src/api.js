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

// Shared SSE frame reader — same logic as streamChat, extracted so upload
// and sync can reuse it without duplicating the buffer/parse loop.
async function readSSE(response, label, onEvent) {
  if (!response.ok) throw await fail(response, label);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminated = false;
  
  const processEvent = (data) => {
    onEvent(data);
    if (data.type === "response" || data.type === "error") {
      terminated = true;
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop();
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (line) processEvent(JSON.parse(line.slice("data: ".length)));
    }
  }
  if (buffer.trim()) {
    const line = buffer.split("\n").find((l) => l.startsWith("data: "));
    if (line) processEvent(JSON.parse(line.slice("data: ".length)));
  }
  if (!terminated) {
    throw new Error(`${label}: Stream terminated unexpectedly before completion.`);
  }
}

// SSE GET — for endpoints that stream progress (driver, score-history).
// Returns the "complete" event's payload, calling onEvent for progress.
export async function streamGet(path, onEvent, signal) {
  const response = await fetch(path, signal ? { signal } : undefined);
  let result = null;
  await readSSE(response, path, (event) => {
    if (event.type === "complete") result = event.payload;
    else if (event.type === "error") throw new Error(event.detail);
    else if (onEvent) onEvent(event);
  });
  if (result === null) throw new Error("stream ended without completion");
  return result;
}

// Upload (UI-SPEC decision 3, view 7): streams SSE progress events as each
// file is imported, then a terminal "complete" event with the full result.
export async function streamUpload(formData, onEvent) {
  const response = await fetch("/api/laps/upload", { method: "POST", body: formData });
  await readSSE(response, "upload", onEvent);
}

// Sync: streams SSE progress as cohorts are discovered and laps imported.
export async function streamSync(payload, onEvent) {
  const response = await fetch("/api/sync", {
    method: "POST",
    headers: payload ? { "Content-Type": "application/json" } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
  });
  await readSSE(response, "sync", onEvent);
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
  await readSSE(response, "chat message", onEvent);
}
