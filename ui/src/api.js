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
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `${response.status} on chat message`);
  }
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
