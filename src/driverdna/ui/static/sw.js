// DriverDNA service worker (U7 mobile/PWA, docs/DEPLOY-SPEC.md Track M
// item 4, docs/UI-V3-PLAN.md Track A5). One binding rule, non-negotiable:
//
//   Cache the shell, never the numbers.
//
// - /api/* is ALWAYS network-only: never read from, never written to, any
//   cache this worker controls. The server already sets Cache-Control:
//   no-store on every API response (DEPLOY-SPEC H1); this is a second,
//   independent enforcement of the same guarantee at the
//   network-interception layer, so a stale finding can never be served as
//   a current one — the failure mode this whole product exists to
//   prevent, and worse offline than online because there'd be no visible
//   cue.
// - Everything else (the built JS/CSS/fonts/icons/manifest/shell HTML) is
//   cached opportunistically as it's actually fetched — a runtime cache,
//   not a precompiled precache list, because Vite content-hashes build
//   filenames and this hand-written file can't know them in advance.
//   Network-first, falling back to the cache only when the network fetch
//   fails: a fresh deploy is always picked up while online (never stuck
//   behind a stale cached shell), and the cached copy is what makes the
//   installed app still open while offline.

const CACHE_NAME = "driverdna-shell-v1";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return; // never intercept a write
  if (url.origin !== self.location.origin) return; // same-origin only (trust gate 5)
  if (url.pathname.startsWith("/api/")) return; // the binding rule — network-only, always

  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(event.request);
      try {
        const response = await fetch(event.request);
        if (response.ok) cache.put(event.request, response.clone());
        return response;
      } catch (err) {
        if (cached) return cached;
        throw err;
      }
    })
  );
});
