# Replit migration analysis

Date: 2026-08-05
Status: analysis only (no code changes)

## Context

The owner wants to iterate faster from a phone and reduce Claude token burn.
The current Oracle VM + Cloudflare Tunnel deployment works but requires SSH
for any management. Replit offers a mobile app with terminal, editor, and
preview pane, making it a viable platform for phone-based development and
hosting.

This doc covers what it would take to move DriverDNA onto Replit, what
changes, and what breaks.

## What works without changes

1. **The engine runs as-is.** Pure Python, no native extensions beyond numpy
   (which Replit supports). All 750+ tests, the CLI, and the full M0-M7
   pipeline work on any Python 3.11+ environment.

2. **No Node.js needed at deploy time.** The built SPA is already committed
   at `src/driverdna/ui/static/`. A bare `pip install -e ".[ui,ai-gemini]"`
   ships the app ready to serve.

3. **SQLite is the right backend.** Single-tenant, no Postgres needed. The
   DB auto-migrates on first connect.

4. **Port binding.** The CLI already reads `$PORT` from the environment
   (Replit sets this automatically).

5. **Auth interlock.** Binding `0.0.0.0` (which Replit requires) triggers the
   fail-closed interlock — exactly what you want on a public URL.
   `DRIVERDNA_SESSION_SECRET` in Replit Secrets is all that's needed.

6. **Gemini provider.** Already built, live-verified (A38), and cheaper than
   Claude for coaching/chat iteration.

## What needs configuring

### Replit Secrets (environment variables)

| Secret                       | Required | Notes                                      |
| ---------------------------- | -------- | ------------------------------------------ |
| `DRIVERDNA_SESSION_SECRET`   | Yes      | App refuses to start on 0.0.0.0 without it |
| `GEMINI_API_KEY`             | For AI   | Coach/chat provider                        |
| `GARAGE61_TOKEN`             | For sync | Lap data sync from Garage61                |
| `DRIVERDNA_DATABASE_URL`     | No       | Defaults to `driverdna.db` in working dir  |

### `.replit` file (to be created if adopting)

```toml
run = "driverdna ui --host 0.0.0.0 --port 8080 --db /home/runner/data/driverdna.db"
language = "python3"

[env]
DRIVERDNA_BLOB_ROOT = "/home/runner/data/driverdna.db.blobs"

[nix]
channel = "stable-24_05"

[deployment]
run = "driverdna ui --host 0.0.0.0 --port 8080 --db /home/runner/data/driverdna.db"
```

Install step: `pip install -e ".[ui,ai-gemini]"`

### Persistent storage

Both the SQLite database and the blob sidecar (`<db>.blobs/`, one `.npz`
per lap, ~300-580 KB each) must survive container restarts. Replit persists
`/home/runner/`, so placing the DB at `/home/runner/data/driverdna.db` is
correct. Set `DRIVERDNA_BLOB_ROOT` to match.

## What does NOT apply on Replit

| Oracle VM concern          | Replit equivalent               |
| -------------------------- | ------------------------------- |
| `--behind-proxy`           | Not needed (Replit's proxy is external, not on 127.0.0.1) |
| Cloudflare Tunnel          | Replit provides HTTPS endpoint  |
| systemd service            | `.replit` `run` command         |
| `/etc/driverdna/driverdna.env` | Replit Secrets              |
| Daily SQLite backup timer  | Manual or Replit scheduled jobs |
| Firewall / `iptables`      | Replit handles networking       |

## Trust gates

Five trust gates are enforced by tests. Their status on Replit:

| Gate | What it enforces | Replit status |
| ---- | ---------------- | ------------- |
| 1-2  | No `https://` in HTML/JS/CSS `src`/`href` | **Passes.** The SPA is self-contained. |
| 3    | Self-hosted fonts (IBM Plex via `@fontsource`) | **Passes.** Bundled by Vite, no CDN. |
| 4    | PWA manifest + service worker present | **Passes.** Already committed. |
| 5    | Zero non-localhost requests from the SPA (Playwright) | **Passes if Chromium is available.** Skips gracefully otherwise. |

**Risk:** If Replit injects analytics scripts, tracking pixels, or a banner
into served pages, trust gate 5 would fail. This has not been observed on
Replit's paid plans but should be verified.

## Constraints to preserve

1. **Single worker only.** Chat sessions live in an in-process dict (bounded
   at 8, 1-hour TTL). Do not use multi-worker or auto-scaling deployments.
   Replit's default single-process model is correct.

2. **No external requests from the SPA.** This is a hard architectural
   constraint, not a deployment preference. Any platform feature that phones
   home from the browser violates it.

3. **Secrets are env-only.** Never in the DB, config TOML, logs, or
   committed files. Replit Secrets handles this correctly.

4. **The DB path must be explicit.** The default `driverdna.db` in the
   working dir may not survive Replit restarts. Always pass `--db` pointing
   to `/home/runner/data/`.

## Token-saving strategy (independent of hosting)

The Replit move addresses phone iteration, but token burn is a separate
concern. Recommendations regardless of hosting platform:

- **Use Gemini CLI / Gemini API for routine iteration.** Already built and
  live-verified (A38). Free tier is generous; paid is cheap. Reserve Claude
  for architectural decisions and complex debugging.
- **Replit's built-in AI assistant** handles routine edits (rename, add a
  route, fix a typo) without burning Claude tokens. Not Claude-caliber for
  this project's complexity, but fine for small changes.
- **Batch Claude sessions.** The expensive part is context loading (~900
  tests, dense spec). Come with a clear task list rather than exploring.

## Costs

| Item | Oracle VM (current) | Replit Hacker plan |
| ---- | ------------------- | ------------------ |
| Monthly | Free (Oracle free tier) | ~$7/mo |
| Storage | 47 GB block volume | Replit persistent (limited) |
| Uptime | Always-on (systemd) | Always-on (paid plan) |
| Custom domain | Via Cloudflare Tunnel | Via Replit (paid) |
| SSH access | Yes | No (web terminal only) |
| Phone access | SSH app (clunky) | Replit mobile app |

## Migration path (if adopting)

1. Export the SQLite DB from the VM: `scp driverdna@<vm>:/var/lib/driverdna/driverdna.db .`
2. Export blobs: `scp -r driverdna@<vm>:/var/lib/driverdna/driverdna.db.blobs/ .`
3. Create a Replit project from the GitHub repo.
4. Upload the DB and blobs to `/home/runner/data/`.
5. Set secrets in Replit Secrets.
6. Verify: `driverdna ui --host 0.0.0.0 --port 8080 --db /home/runner/data/driverdna.db`
7. Run `python3 -m pytest` on Replit to confirm the engine is intact.
8. (Optional) Keep the VM as a cold backup — `driverdna store-copy` works
   in both directions.

## Alternatives considered

| Platform | Verdict | Reason |
| -------- | ------- | ------ |
| **Bolt.new** | UI mockup tool only | Generates frontend code; cannot run the Python engine |
| **Lovable** | Poor fit | Same as Bolt; also defaults to Supabase (just migrated off) |
| **Cursor** | Desktop only | Great for development but does not solve the phone problem |
| **Railway** | Viable but no mobile story | Cheaper than Replit at scale, more control, but no mobile app |
| **Fly.io** | Viable, SQLite-friendly (LiteFS) | No phone-friendly management interface |

## Recommendation

Replit is the best fit for the stated constraints (phone iteration, lower
token burn, simpler hosting). The tradeoffs are: ~$7/mo cost (vs free VM),
limited storage (vs 47 GB block volume), and no SSH (vs full shell access).
The engine, trust gates, and architecture are fully compatible.

Keep the Oracle VM as a cold backup until confidence in Replit's persistence
is established. The `store-copy` command makes bidirectional migration safe.
