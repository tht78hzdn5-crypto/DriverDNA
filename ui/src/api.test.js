// Unit tests for the API layer with a stubbed fetch. No browser, no DOM:
// the only browser touchpoints are fetch itself and the 401 broadcast, both
// stubbed here. SSE tests drive the frame reader with chunked bodies.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  UNAUTHENTICATED,
  get,
  send,
  streamChat,
  streamGet,
  streamSync,
} from "./api.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function sseResponse(chunks) {
  const queue = chunks.map(
    (text) => new TextEncoder().encode(text),
  );
  return {
    ok: true,
    status: 200,
    body: {
      getReader() {
        return {
          read: async () =>
            queue.length > 0
              ? { done: false, value: queue.shift() }
              : { done: true, value: undefined },
        };
      },
    },
  };
}

describe("get", () => {
  it("returns the parsed body on success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ laps: 3 })));
    await expect(get("/api/driver")).resolves.toEqual({ laps: 3 });
    expect(fetch).toHaveBeenCalledWith("/api/driver");
  });

  it("throws an error carrying the status and the server detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "nope" }, { ok: false, status: 500 })),
    );
    const error = await get("/api/driver").catch((e) => e);
    expect(error).toBeInstanceOf(Error);
    expect(error.message).toBe("nope");
    expect(error.status).toBe(500);
  });

  it("falls back to 'status on path' when the error body has no detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({}, { ok: false, status: 503 })),
    );
    const error = await get("/api/driver").catch((e) => e);
    expect(error.message).toBe("503 on /api/driver");
  });

  it("marks a 401 unauthenticated and broadcasts it", async () => {
    const dispatch = vi.fn();
    vi.stubGlobal("window", { dispatchEvent: dispatch });
    vi.stubGlobal(
      "CustomEvent",
      class {
        constructor(type) {
          this.type = type;
        }
      },
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({}, { ok: false, status: 401 })),
    );
    const error = await get("/api/driver").catch((e) => e);
    expect(error.kind).toBe(UNAUTHENTICATED);
    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(dispatch.mock.calls[0][0].type).toBe("driverdna:unauthenticated");
  });
});

describe("send", () => {
  it("forwards method, JSON headers, and body", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await send("POST", "/api/notes", { text: "hi" });
    expect(fetchMock).toHaveBeenCalledWith("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "hi" }),
    });
  });

  it("sends no content type or body without one", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await send("DELETE", "/api/notes/1");
    expect(fetchMock).toHaveBeenCalledWith("/api/notes/1", {
      method: "DELETE",
      headers: undefined,
      body: undefined,
    });
  });
});

describe("streamGet", () => {
  it("returns the complete event payload and reports progress in order", async () => {
    const seen = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'data: {"type":"progress","pct":10}\n\n',
          'data: {"type":"complete","payload":{"laps":7}}\n\n',
        ]),
      ),
    );
    const result = await streamGet("/api/driver", (e) => seen.push(e));
    expect(result).toEqual({ laps: 7 });
    expect(seen).toEqual([{ type: "progress", pct: 10 }]);
  });

  it("reassembles a frame split across chunks", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'data: {"type":"prog',
          'ress","pct":50}\n\ndata: {"type":"complete","payload":1}\n\n',
        ]),
      ),
    );
    await expect(streamGet("/api/driver")).resolves.toBe(1);
  });

  it("throws on an error event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse(['data: {"type":"error","detail":"boom"}\n\n']),
      ),
    );
    await expect(streamGet("/api/driver")).rejects.toThrow("boom");
  });

  it("throws when the stream ends without a terminal event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse(['data: {"type":"progress","pct":10}\n\n']),
      ),
    );
    // readSSE throws first: streamGet's own "without completion" check is
    // unreachable when the stream ends without a terminal event.
    await expect(streamGet("/api/driver")).rejects.toThrow(
      "Stream terminated unexpectedly before completion",
    );
  });
});

describe("streamSync and streamChat", () => {
  it("posts the payload and consumes progress through completion", async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse([
        'data: {"type":"progress","phase":"discovering"}\n\n',
        'data: {"type":"complete"}\n\n',
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const seen = [];
    await streamSync({ car: "Mustang" }, (e) => seen.push(e));
    expect(fetchMock).toHaveBeenCalledWith("/api/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ car: "Mustang" }),
    });
    // streamSync passes onEvent straight through, so it sees the complete
    // event too — unlike streamGet, which filters it out.
    expect(seen).toEqual([
      { type: "progress", phase: "discovering" },
      { type: "complete" },
    ]);
  });

  it("posts chat text to the session endpoint", async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse(['data: {"type":"complete"}\n\n']),
    );
    vi.stubGlobal("fetch", fetchMock);
    await streamChat("abc", "hello", () => {});
    expect(fetchMock).toHaveBeenCalledWith("/api/chat/sessions/abc/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "hello" }),
    });
  });
});
