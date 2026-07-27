# DriverDNA — Deployment, Mobile & Provider Spec (design stage)

**Status: design adopted 2026-07-26 (owner decisions recorded below), build
not started.** Governs three tracks that were, until today, on UI-SPEC's
*v1-only deferred* out-of-scope list: **P** (a second AI provider — Gemini),
**M** (mobile / PWA), **H** (hosted deployment + authentication).

This document is the *how* for those three tracks only. It does not amend the
engine: `docs/SPEC.md` stays authoritative for measurement,
`docs/ARCHITECTURE_VISION.md` stays the constitution, `docs/UI-SPEC.md` stays
authoritative for what the interface may render. Where this document and any
of those three conflict, they win.

## Why this is allowed to happen now

A17 (SPEC.md, 2026-07-20) split UI-SPEC's out-of-scope list in two.
"Authentication and multi-user, hosted deployment, mobile app" went into the
**v1-only deferred** half, revisitable on two conditions: *post-M6* and
*post-blind-test*. Both are met — M6 (and M7) are built, and the Spa blind
acceptance test ran on 2026-07-21 (A18), catching and fixing a real ranker
bug. This is the sanctioned revisit, not a bypass.

A17's own condition on any revisit is binding here: **the permanent
exclusions stay intact.** Nothing below edits a measurement, computes a
figure client-side, blends a score, or gives setup advice.

### The one framing that keeps philosophy #8 whole

Philosophy #8 is "personal instrument, not a product." A17 refined it to
"personal instrument *first*." Hosting DriverDNA on a public network is the
first change that could be mistaken for productization, so it is defined
narrowly and mechanically:

> **DriverDNA stays single-tenant.** Auth is a lock on one driver's own
> door, not a user system. There is no user table, no registration, no
> tenant column, no per-user data partitioning, and no second identity.
> The driver identity in the data model remains exactly what it is today —
> a `driver` string on a lap row, unrelated to who is logged in.

If a future change needs a second real user, that is productization and it
goes back to the owner as its own decision, with its own amendment. This
spec must not be cited as precedent for it.

## Owner decisions (2026-07-26)

Four forks were surfaced before any design work; all four were answered by
the owner. Recorded here at decision time per CLAUDE.md's decision
discipline, mirrored in SPEC.md A23 and PROJECT-BRIEF.md's decision log.

1. **Host on an Oracle Cloud "Always Free" VM.** The engine and the SQLite
   DB run in the cloud, always on. Rejected: home machine + tunnel (data
   never leaves, but the PC must be awake); free PaaS (Render's free tier
   has no persistent disk and sleeps — the DB would be destroyed on every
   restart; Azure Static Web Apps can host the SPA but not a scipy/SQLite
   Python engine).
2. **Gemini free tier, tradeoff accepted.** Google's own pricing page states
   free-tier content **is** used to improve their products; paid tier
   content is not. The owner accepts this for personal driving telemetry.
   This is a stated decision, not an oversight — see "Data exposure" below
   for exactly what leaves the machine.
3. **Mobile = read + chat subset.** Driver home, Driver Model, cohort
   findings and chat get real phone layouts. Corner drill-down, evidence
   tables, config and upload stay desktop-shaped but must remain reachable
   and legible (never broken, just not optimized).
4. **PWA, home-screen install.** Manifest + service worker over the existing
   SPA. No native shell, no store, no Apple Developer account.

---

# Track P — Provider abstraction + Gemini

## P0 — what already makes this cheap

The provider seam exists and is clean:

- `coach/provider.py`: `CoachProvider.complete(system, user) -> str`, plus
  `ClaudeCoachProvider`.
- `chat/session.py`: `ChatProvider.chat_step(system, messages, tools) ->
  {"text", "tool_calls", "raw_content"}`, plus `ClaudeChatProvider`.
- Both are injected (`cli.py`, and `create_app(..., chat_provider_factory=)`),
  and every existing test already runs against a mock.

Critically, **nothing about grounding is provider-specific.** The validators
in `coach/validate.py`, `coach/grounding.py` and `ChatSession._validate` work
on the returned text against the payload's own number pool and ID universe.
A different model does not get different rules; it gets the same rejection
machinery.

## P1 — the work

1. **Config.** Add `coach.provider: Literal["claude", "gemini"] = "gemini"`
   and split the model field: `coach.model` stays the Claude model,
   `coach.gemini_model` the Gemini one. Both carry documented defaults and
   flow through `ConfigStore` like every other parameter (versioned,
   reversible, audited) — no new mechanism.
   Do **not** pin a Gemini model name from memory: read the current
   free-tier model list off `ai.google.dev/gemini-api/docs/pricing` at build
   time and record the pinned name plus the date it was verified. As of
   2026-07-26 the free tier is Flash / Flash-Lite class only; the Pro models
   are paid.
2. **`GeminiCoachProvider`** in `coach/provider.py`. Same lazy-import
   discipline as the Claude one (`google-genai` imported inside `__init__`,
   never at module import), same env-only key: `GEMINI_API_KEY`, absent →
   a loud `RuntimeError` naming the variable. Never persisted, printed or
   logged — the existing non-negotiable extends to it verbatim.
3. **`GeminiChatProvider`** in `chat/session.py` — the only genuinely
   fiddly piece. `ChatSession._messages` is an Anthropic-shaped transcript
   (`{"role": "user", "content": [{"type": "tool_result", ...}]}`, plus the
   opaque `raw_content` echo of the assistant's tool-use turn).
   **Decision: translate inside the provider, do not refactor the
   transcript.** `GeminiChatProvider.chat_step` accepts the Anthropic-shaped
   `messages` and converts to Gemini's `contents` (function-call /
   function-response parts) on the way in, and converts the response back to
   the `{"text", "tool_calls", "raw_content"}` contract on the way out;
   `raw_content` holds whatever that provider needs to echo its own tool
   turn back.
   *Rejected:* a neutral internal transcript with per-provider adapters. It
   is the cleaner long-term shape, but it edits M5 code that is tested and
   working, and would make the Claude path a rewrite rather than a
   no-change. Revisit if a third provider ever appears — at three, the
   translation matrix stops paying.
4. **Tool schema translation.** `TOOL_DEFS` (`chat/tools.py`) uses
   Anthropic's `input_schema`. Gemini's `FunctionDeclaration` takes an
   OpenAPI-subset `parameters`. Every current tool schema is a flat object
   of required strings, so translation is mechanical and lossless — but it
   must be a real function with a test (`test_gemini_tool_translation`), not
   a dict rename inline, and it must raise on any schema keyword it cannot
   faithfully translate rather than silently dropping it. A silently dropped
   `required` is exactly the kind of quiet degradation this project doesn't
   allow.
5. **Free-tier rate limits are a design input, not an afterthought.** A chat
   turn can issue up to `MAX_TOOL_STEPS` (8) provider calls, and free-tier
   RPM is low (single-digit to low-teens depending on model and the day —
   read the live number from AI Studio, don't hardcode a blog's figure).
   The provider must handle HTTP 429 with bounded exponential backoff and,
   on exhaustion, surface an explicit "rate limited" error. It must never
   silently return partial or empty text — an empty reply would enter the
   validator and be rejected as a grounding failure, blaming the wrong thing.
6. **Provenance.** Migration 006: `ALTER TABLE coach_outputs ADD COLUMN
   provider TEXT NOT NULL DEFAULT 'claude'` (the default is honest —
   every existing row was Claude). `driverdna history` and the coach output
   display show it. Which model produced a stored explanation is part of the
   audit trail, not incidental.
7. **Packaging.** `anthropic` moves out of the hard `dependencies` list into
   an optional extra alongside `google-genai`: `ai-claude` and `ai-gemini`.
   Neither is needed to run the engine, and the engine is the product. The
   CLI already fails loudly and usefully on a missing optional dependency
   (`ui` extra) — reuse that pattern verbatim.

## P1 done-criteria

- Every existing coach/chat test passes unchanged against the mocked
  provider (proof the seam moved nothing).
- A `GeminiChatProvider` unit test drives a recorded/mocked Gemini-shaped
  response through the full translation both ways, including a two-tool-call
  turn and a tool-result round trip.
- **A live run against the real fixture cohort** with `GEMINI_API_KEY` set:
  `driverdna coach` produces output that passes the strict validator
  unmodified. This is the acceptance gate that matters — a weaker model is
  allowed to be rejected, but a provider that can never satisfy the
  grounding contract is not usable, and we should learn that from a real
  run rather than assume it. Record the observed rejection/regeneration rate
  in STATUS.md; if the free-tier model needs the second attempt routinely,
  say so plainly rather than tuning the validator to accept it.
- Tests still never call a live API and never require a secret.

## Data exposure — stated, not buried

With decision 2, on every `coach` or `chat` invocation the following leaves
the machine and may be used to improve Google's models: the deterministic
payload (findings, evidence IDs, corner IDs, metric values, driver-model
beliefs, coaching principles, incidents), the driver/car/track strings, and
the chat text. `include_raw_traces` stays **false** by default; raw telemetry
arrays are not sent unless the owner explicitly turns that on.
`GARAGE61_TOKEN`, API keys and the DB itself never leave. Switching
`coach.provider` back to `claude`, or to a paid Gemini tier, changes this and
is a one-key config change through the audited path.

---

# Track M — Mobile (U5)

The SPA is closer to mobile-ready than expected: `index.html` already carries
the viewport meta, layout is mostly CSS grid with `auto-fill` minmax, and the
Driver Model pyramid is an already-responsive SVG. The blockers are
`#root { max-width: 64rem }` with fixed rem padding, the fixed-column grids
(`.lossrow`), the header nav (which grows to ~8 links on a cohort route), and
the dense evidence tables.

## U5 work

1. **Responsive pass** on `ui/src/app.css`, no view rewrites:
   - fluid root padding; single-column stacking below ~48rem
   - `.lossrow` and the other fixed-column grids collapse to stacked rows
   - the topbar nav becomes horizontally scrollable (not a hamburger — a
     hamburger hides where you are, and this UI's whole personality is that
     the next fact is one tap away)
   - tap targets ≥44px on everything interactive, chat input included
   - wide tables get `overflow-x: auto` on their own container, so the page
     body never scrolls sideways
   - `env(safe-area-inset-*)` respected for iOS notch/home indicator
2. **The four subset views get real phone layouts** (decision 3): driver
   home, `#/model`, `#/cohort/:slug`, `#/chat`. The rest must remain
   legible and reachable — verified, not assumed (see done-criteria).
3. **PWA shell.** `manifest.webmanifest` (standalone display, dark
   theme-color from `ui/tokens.json` — never a second hardcoded palette),
   maskable icons, `apple-touch-icon`. Vite emits them into the same
   in-package static dir; node stays a build-time-only dependency.
4. **Service worker — one binding rule.**

   > **Cache the shell, never the numbers.** Static build assets (hashed JS,
   > CSS, fonts, icons) are precached. Every `/api/*` response is
   > network-only, and the API sets `Cache-Control: no-store`.

   A stale cached finding is a wrong number presented as a current one —
   that is the failure mode this whole project exists to avoid, and it is
   worse offline because there is no visible cue. Offline, the app shows an
   explicit "not connected — no current data" state, in the same register as
   the existing empty states (direction, not apology). It never shows the
   last numbers it saw.
5. **HTTPS is a hard precondition**, not polish: service workers and iOS
   home-screen install both require a secure origin. Track H supplies it.

## U5 done-criteria

- The render-parity crawler (`tests/test_render_parity.py`) runs a second
  pass at a 390×844 viewport: same guarantee, every on-screen number
  traceable to the payload, plus no horizontal body overflow on any route.
- Trust gate 5's Playwright test is amended (see below) and stays green.
- Real device check on the owner's phone: install to home screen, open
  offline, confirm the offline state says "no current data" and shows no
  stale figures.

## Trust gate 5 must be restated, not weakened

UI-SPEC principle 8 and trust gate 5 currently read "fully offline / all
non-localhost network blocked." Once the app is served from a hostname, that
literal wording is false while the property it protects is unchanged. The
property is: **the SPA makes zero third-party requests — every asset and
every byte of data comes from the app's own origin.** The test changes from
"block all non-localhost" to "block all non-same-origin"; CDNs, fonts,
analytics and telemetry remain categorically forbidden. This is a wording
correction to keep an existing guarantee testable, not a relaxation.

---

# Track H — Hosting + hardening

Target: an Oracle Cloud Always Free VM (decision 1). Note the free
allocation was **halved on 2026-06-15** — Ampere A1 Flex is now 2 OCPU /
12 GB (was 4/24), with 200 GB block volume including a 47 GB minimum boot
volume. Still far more than DriverDNA needs; the constraint worth checking
at build time is regional A1 capacity, which is the usual reason a free
instance won't launch.

## H1 — make the app safe to expose (before any exposure)

> **Status: BUILT 2026-07-27** (SPEC.md A31). All five items below are
> implemented and tested. Read the "H1 as built" subsection after them for
> what changed on the way, what the platform turned out to be, and the one
> deployment step that must happen *before* this reaches `main`.

This lands and is verified **entirely locally**. Nothing is deployed until
H1's done-criteria pass.

1. **`driverdna ui --host` with a fail-closed interlock.** The host is
   currently hardcoded to `127.0.0.1` (`cli.py`). Add `--host`, and make the
   command **refuse to bind a non-loopback address unless authentication is
   configured**, with an error that names what's missing. A misconfiguration
   must not be able to publish an unauthenticated instrument to the internet.
2. **App-level auth, single-driver.** A `DRIVERDNA_ACCESS_TOKEN` env
   secret (env-only, same rule as every other secret) exchanged at
   `POST /api/auth/login` for an HttpOnly, Secure, SameSite=Lax session
   cookie; constant-time comparison (`hmac.compare_digest`); signed,
   expiring session value; `POST /api/auth/logout`. One FastAPI dependency
   guards every route except the login endpoint and the static shell. No
   user table, no registration, no password reset — see the single-tenant
   framing above.
3. **Write-path hardening.** The write endpoints (`/api/laps/upload`,
   `/api/findings/{id}/annotate`, `/api/config/*`, `/api/chat/*`) get, in
   addition to auth: an upload size cap and content-type check, a rate limit
   on `/api/chat/*` and any coach invocation (they cost money and quota, and
   are the only endpoints that reach a third party), and `no-store` on every
   API response. `/api/config/apply` keeps requiring the explicit confirm it
   already requires — auth changes nothing about the ConfigStore path.
4. **Single worker, stated as a constraint.** Chat sessions live in an
   in-process dict (`create_app`'s `chat_sessions`) and the chat DB
   connection is a long-lived `check_same_thread=False` handle. The service
   runs `uvicorn --workers 1`. This is written into the systemd unit and
   documented in the deploy notes, because a future "let's add workers"
   would break chat silently rather than loudly.
5. **Secrets on the box.** `GEMINI_API_KEY`, `GARAGE61_TOKEN`,
   `DRIVERDNA_ACCESS_TOKEN` in a `0600` systemd `EnvironmentFile` owned by
   the service user. Never in the DB, never in config TOML, never in logs.
   Log format reviewed once for accidental secret echo.

## H1 as built (2026-07-27)

Implemented as specified above, with the deviations and findings below
flagged at build time rather than left to be discovered.

**The platform is not the one this document assumed.** Decision 1 chose an
Oracle Cloud Always Free VM with SQLite, reached over Tailscale. What
actually exists is **Google Cloud Run** (`northamerica-northeast1`, service
`driverdna`, deployed from `main` by `.github/workflows/deploy.yml`) with
**Supabase Postgres** as the store (SPEC.md A23). That move was never
recorded in an amendment — a decision-discipline gap noted here so the next
reader is not misled by the Oracle/Tailscale text in H2/H3, which describes
a deployment that does not exist. H2 and H3 are **not** built and now
describe the wrong target; revisit them against Cloud Run when they are
picked up.

**The build order was violated before this milestone started.** H1 says "H1
must precede any exposure, by definition." The Cloud Run deploy landed
first, so between then and now the app was reachable at a public hostname
with zero application-level auth, protected only by Cloud Run's
`--no-allow-unauthenticated` IAM flag. That flag is untouched by this work
(owner's call, 2026-07-27: build auth first, flip exposure separately).

**Deviations from the five items, and why:**

1. **One *app-level* dependency, not a per-route one.** Item 2 says "one
   FastAPI dependency guards every route". Implemented as
   `FastAPI(dependencies=[Depends(guard)])`, which is that, and additionally
   covers any route added later — the failure mode the done-criterion's
   route-table test exists to catch. The guard allowlists `/api/auth/login`
   and `/api/auth/status` by path.
2. **The static shell is public**, as item 2 allows. It is a `StaticFiles`
   mount rather than a route, so the guard never sees it. Correct: the shell
   is what renders the sign-in screen.
3. **`Secure` is conditional, and read from `X-Forwarded-Proto`.** Cloud Run
   terminates TLS, and uvicorn only trusts forwarded headers from
   `forwarded_allow_ips` (which does not include a Cloud Run front end), so
   the app cannot read the scheme off the request URL. Reading the header
   directly is what stops the session cookie going out unmarked over a real
   HTTPS deployment. On plain-http loopback the flag is omitted so local
   development still works.
4. **Login throttling was added**, beyond item 3's list. A single-secret
   endpoint on a public URL needs it. Per client address, short lockout by
   default — a long one would let a stranger keep the driver out of their
   own cockpit.
5. **The session is stateless.** No session table, no server-side store: the
   cookie carries an expiry and its signature, and the signing key is
   derived from the passphrase. This was not specified either way and
   matters here — Cloud Run can run more than one instance, and a
   server-side session store would break across them. It also makes
   rotating `DRIVERDNA_ACCESS_TOKEN` the revocation path.
6. **Item 4's single-worker constraint is necessary but no longer
   sufficient.** It was written for a systemd unit. Cloud Run scales to N
   *instances*, which `--workers 1` does not address. Auth is unaffected
   (stateless), but `chat_sessions` and both in-process limiters are
   per-instance. **Recommend `--max-instances=1` on the service**; this is a
   pre-existing latent bug, not one this milestone introduced.
7. **The upload cap measures parsed size, not wire size.** `UploadFile.size`
   is what Starlette's multipart parser actually read, so the body has been
   received (spooled to disk) by the time it can be measured. What the cap
   bounds is what gets parsed and imported.

**An identity provider was considered and rejected on evidence.** Auth0,
Clerk, Firebase and Supabase Auth are all free at this scale, and all are
mechanically excluded from the browser by two existing tests:
`tests/test_ui_static.py` asserts the built bundle contains no `https://`
(fails in CI, no browser needed), and `tests/test_offline.py` aborts every
non-same-origin browser request. A server-side OIDC flow would pass both;
it was rejected because for one driver it buys MFA in exchange for a vendor,
a dependency, a redirect URI pinned to the Cloud Run hostname, and a user
model this document forbids. The chosen scheme adds no third-party origin at
either level, so **trust gates 5a and 5b needed no amendment**.

**Done-criteria status:**

- ✅ With auth unconfigured, `driverdna ui --host 0.0.0.0` refuses and says
  why (`tests/test_auth_cli.py`).
- ✅ Every `/api/*` route returns 401 without a session, via a test that
  enumerates `app.routes` (`tests/test_auth_api.py`).
- ✅ Both UI-SPEC browser trust gates green, plus a browser test of the gate
  itself (`tests/test_auth_ui.py`), including one proving the gate tests are
  not vacuous.
- ⬜ Unreachable-from-outside check — belongs to H2/H3, which are not built.
- ⬜ Full suite on the deployment against the real DB — owner's to run.

### ⚠️ Required before this reaches `main`

`Dockerfile` runs `driverdna ui --host 0.0.0.0`. The interlock now refuses
that bind with no passphrase configured, so **the Cloud Run service will fail
to start unless `DRIVERDNA_ACCESS_TOKEN` is set in its environment.** That is
the interlock working as designed; it is also a sequencing hazard, because
`.github/workflows/deploy.yml` deploys on every push to `main`.

Order: create the secret, set it on the service, confirm it survives a
revision deployed by `deploy-cloudrun@v2` (which can clear env vars it is not
told about — prefer Secret Manager with `--set-secrets`, declared in the
workflow, over a one-off `--set-env-vars`), and only then merge. Generate the
passphrase with real entropy; it is the only thing between the internet and
the instrument once exposure is flipped on.

## H2 — network shape

Two layers, and the recommendation is to use both:

- **Reachability: Tailscale.** Install on the VM, phone joins the tailnet,
  and `tailscale serve` publishes the app on a `*.ts.net` name **with a
  valid TLS certificate** — which is what makes the PWA installable. The
  VM's OCI security list and host firewall keep **zero** inbound ports open;
  the tunnel is outbound. Free for personal use (6 users, unlimited
  user-owned devices as of 2026-04-08), needs no domain name, and the app is
  not on the public internet at all.
- **Optional public hostname: Cloudflare Tunnel + Cloudflare Access.** Also
  outbound-only, with identity checks (email OTP or Google/GitHub SSO)
  enforced at Cloudflare's edge before a request ever reaches the VM; Access
  is free up to 50 users. **One honest caveat: Access requires a domain on
  your Cloudflare account, so this is the single component of the plan that
  is not literally free** (~$10/yr for a domain). If a public URL isn't
  wanted, skip this layer entirely — Tailscale alone satisfies the
  requirement.

Whichever is used, H1's app-level auth stays on. Edge identity is a good
outer wall, not a reason for the app to trust an unauthenticated request.
If Access is adopted, additionally verify its `Cf-Access-Jwt-Assertion`
header against Cloudflare's public keys and allowlist the single owner email
— defence in depth, and it costs one small dependency plus a test.

## H3 — operations

- **systemd unit** for `driverdna ui --host 127.0.0.1` behind the tunnel
  (the tunnel connects to loopback; the interlock in H1 is satisfied by the
  auth config, not by the bind address), `Restart=always`, hardened unit
  options (`ProtectSystem`, `NoNewPrivileges`, `PrivateTmp`, dedicated user).
- **Lap intake needs no upload path from the phone.** `driverdna sync` runs
  on the VM directly against Garage61 with `GARAGE61_TOKEN` — a systemd
  timer, idempotent by the existing content-hash dedup. `#/upload` remains
  for manual/reference CSVs and now works from the phone browser.
- **Backups.** `sqlite3 .backup` on a timer to the block volume, retained N
  copies, plus an occasional pull to the owner's machine. The DB is
  reconstructible from source CSVs by a deterministic engine, but the
  Driver Model's dated history and chat/coach transcripts are not — those
  are the irreplaceable rows.
- **ARM64 note:** `numpy`/`scipy` ship aarch64 manylinux wheels; no source
  builds expected. Verify at deploy, don't assume.
- **Deploy runbook** written as `docs/DEPLOY-RUNBOOK.md` at H3 time — exact
  commands, from empty tenancy to installed PWA, so the box is rebuildable
  rather than a pet.

## H done-criteria

- With auth unconfigured, `driverdna ui --host 0.0.0.0` refuses to start
  and says why (tested).
- Every `/api/*` route returns 401 without a session (a test that enumerates
  the app's own route table, so a future endpoint can't be forgotten).
- An unauthenticated request from outside the tailnet cannot reach the app
  at all — verified from a device off the tailnet, not reasoned about.
- The full local test suite passes on the VM, against the real DB.
- Determinism re-verified on ARM: two imports, byte-identical reports —
  the existing mechanical check, run on the new architecture.

---

## Build order

Strict, and each step is independently useful:

**P1 (Gemini, entirely local)** → **H1 (auth + interlock, entirely local)**
→ **U5 (responsive + PWA, verified over a Tailscale HTTPS origin from the
owner's own machine)** → **H2/H3 (VM, tunnel, timers, backups, runbook)**.

Rationale for the order: P1 is the lowest-risk and highest-value change and
touches no security surface. H1 must precede any exposure, by definition.
U5 needs HTTPS but not the VM — Tailscale over the home machine supplies a
real certificate, so the whole mobile experience can be validated before any
cloud resource exists. H2/H3 are then a move, not a rewrite.

Each track ends the way every milestone here ends: tests green **and** its
inspectable artifact reviewed — for P1 a real Gemini coach run that passes
the validator, for U5 the mobile crawler pass plus an installed home-screen
app, for H the external unreachability check.

## Out of scope for these tracks

Permanent (unchanged, per A17): editing measurements, client-side
computation of any figure, blended scores, setup advice.

Explicitly excluded here, and not deferred-with-a-wink:

- **Multi-user in any form.** No user table, no second identity, no sharing.
- **A native app shell** (Capacitor/Tauri) — decision 4 chose the PWA. Worth
  noting the reason it stays excluded is partly economic: iOS installs
  beyond 7-day sideloads need a $99/yr Apple Developer account, and the PWA
  gets the same home-screen result for nothing.
- **Postgres or any DB migration.** SQLite on a persistent disk is correct
  for one driver; the free-PaaS options that would have forced this were
  rejected in decision 1.
- **Server-side rendering, CDN, analytics, error telemetry.** All would
  violate the same-origin guarantee that replaces trust gate 5's offline
  wording.
- **Automatic AI refresh** (already out of scope in SPEC.md, restated
  because a hosted always-on box makes it tempting): coach and chat stay
  on-demand only, invoked by the driver.
