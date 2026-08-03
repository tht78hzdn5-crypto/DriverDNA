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

> **2026-07-29 update (SPEC.md A35, `docs/UI-SPEC.md` A35, `docs/UI-V3-PLAN.md`
> Track C):** built as scheduled below, plus a new bring-your-own-key layer
> not in this document's original design — the owner's Gemini identity ask
> ("users spend their own usage") turned out not to be deliverable via
> Google OAuth for a third-party app, so BYOK is the resolution. Track P
> below is otherwise unchanged and remains the design of record for the
> provider swap itself.

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

**Built 2026-08-02** (docs/UI-V3-PLAN.md Track C1) — the seam, translation,
and BYOK layer are built and mock-tested; the live acceptance run
**completed 2026-08-02** (Track C3, SPEC.md A36) — see below:

- `coach.provider` (default `"gemini"`, matching this doc's own text) and
  `coach.gemini_model` (default `gemini-3.5-flash`) landed in `config.py`.
  Model pinned from `ai.google.dev/gemini-api/docs/pricing`, verified
  2026-08-02: `gemini-3.5-flash`/`gemini-3.5-flash-lite` are the current
  free-tier Flash-class models; Pro is paid-only. Per this doc's own
  standing rule, this is a live-fetched pin, not a memorized name.
- `GeminiCoachProvider`/`GeminiChatProvider` built exactly to this doc's
  design (lazy SDK import, env-only key, transcript translation inside the
  provider). The real `google-genai` SDK's actual surface was verified by
  direct introspection of the installed 1.x/2.x package (`Client`,
  `models.generate_content`, `types.GenerateContentConfig/Tool/
  FunctionDeclaration/Content/Part/FunctionCall/FunctionResponse`,
  `AutomaticFunctionCallingConfig`, `errors.ClientError.code`) rather than
  assumed from training data or possibly-stale fetched docs — a newer
  `client.interactions.create` API surface also exists in the current SDK
  and was deliberately NOT used, since this doc's own design (
  "FunctionDeclaration... OpenAPI-subset parameters") assumes the classic
  `generate_content` shape, which remains present and is the lower-risk,
  more conservative choice.
- Tool-schema translation (`chat/gemini_tools.py`) is a real function
  (`translate_tool_schema`) tested against every real TOOL_DEFS schema
  (`tests/test_gemini_tool_translation.py`) and against real
  `google.genai.types.Schema`/`FunctionDeclaration`/`Tool` construction
  (SDK-validated, not just a plain-dict shape check) — raises on any
  keyword it doesn't recognize, per this doc's own requirement.
  `tests/test_gemini_chat_provider.py` proves the message translation both
  ways (plain text turns, a two-tool-call turn, a tool-result round trip
  that recovers the original function name Anthropic's own tool_result
  block doesn't carry, rate-limit backoff-then-succeed, backoff exhaustion,
  a non-429 error propagating without retry, and a silently-empty response
  raising rather than entering the validator) — all against real SDK
  response objects, only the network call itself mocked.
  `tests/test_gemini_coach_provider.py` covers the coach's single-turn path
  the same way.
- Migration 013: `coach_outputs.provider TEXT NOT NULL DEFAULT 'claude'`,
  surfaced in `driverdna history`'s output and `store_coach_output`'s new
  `provider` parameter.
- Packaging: `anthropic` moved out of hard `dependencies` into an
  `ai-claude` extra; `google-genai` is a new `ai-gemini` extra. Neither SDK
  is imported at module level anywhere in this codebase (verified by grep),
  so the move is additive — an existing install with `anthropic` already
  present is unaffected.
- **Done 2026-08-02 (Track C3, SPEC.md A36):** the owner supplied a real
  `GEMINI_API_KEY` for one live session (rotated immediately after — never
  persisted, never committed, used only as a transient env var, never
  written to any file in this repo). `driverdna coach` was run against the
  real fixture cohort (`GR86:Spa-Francorchamps`, 11 laps). The first raw
  attempts (5/5) were rejected — but investigation showed the rejections
  traced to two real, fixable defects, not to Gemini being structurally
  unable to satisfy the grounding contract:
  1. `coach.max_tokens` default (4000) silently starved `gemini-3.5-flash`
     (a thinking model whose reasoning tokens share the same budget as
     output text) — empty response, `finish_reason=MAX_TOKENS`. Raised to
     16000; a live diagnostic call proved this alone (with the old prompt)
     restores non-empty structured output.
  2. `coach/provider.py`'s `SYSTEM_PROMPT` had two real ambiguities Gemini
     hit consistently (Claude apparently never triggered either): it read
     the no_signal "never attach confidence" rule as covering ordinary
     `hypotheses[]` entries too (emitting `confidence: null`), and nothing
     told it an `incident_explanations[]` entry must cite its own
     `incident_id` inside its own `evidence_ids`. Both clarified in the
     prompt; `PROMPT_VERSION` `coach-v2` → `coach-v3` — wording only, the
     validator (`coach/validate.py`) was never touched, per this
     repository's absolute rule against loosening it to fit a weaker model.
  **After both fixes: 2/2** live `driverdna coach` runs passed the strict
  validator unmodified on the first attempt. One live grounded chat turn
  through `GeminiChatProvider` also passed on the first attempt (chat
  already had its regenerate-once loop and needed no prompt change),
  citing real evidence. **The acceptance gate this section named is now
  met.** Full detail: SPEC.md A36, `docs/STATUS.md`'s 2026-08-02 snapshot.

**Track C2 built 2026-08-02** (SPEC.md A35, docs/UI-V3-PLAN.md Track C2) —
the per-user BYOK layer this doc didn't originally design (it predates the
owner's decision that "own usage" means bring-your-own-key, not Google
OAuth — see SPEC.md A35 for the investigation that produced that call):

- Migration 014: `user_api_keys` (`owner_user_pk`, `provider`, `ciphertext`,
  `nonce`, `fingerprint`, `created_at`), unique on `(owner_user_pk,
  provider)`. `src/driverdna/coach/keystore.py`: AES-256-GCM
  (`cryptography`, newly explicit in the `ui` extra — stdlib ships no AEAD),
  key-encryption key derived from `DRIVERDNA_SESSION_SECRET` via
  `hashlib.scrypt` with its own fixed domain-separation salt (distinct from
  `ui/auth.py`'s session-signing derivation off the same secret, so the two
  keys can never collide). A fixed, not random, salt is correct for this
  KDF-over-one-shared-secret use (not a password hash) — it must be
  deterministic across restarts or every previously-encrypted key becomes
  undecryptable.
- Every provider class (`ClaudeCoachProvider`, `GeminiCoachProvider`,
  `ClaudeChatProvider`, `GeminiChatProvider`) gained an `api_key: str |
  None = None` constructor parameter, passed straight to the SDK client;
  `None` (every non-BYOK caller, including the CLI) is byte-identical to
  the original env-only behavior. `coach.provider.make_coach_provider` /
  `chat.session.make_chat_provider` centralize the Claude-vs-Gemini branch
  in one place each, reused by the CLI and `ui/api.py`.
  `PUT/GET/DELETE /api/settings/ai-key`: write-only in one direction (PUT
  accepts the raw key once; GET returns only a fingerprint, e.g.
  "AIza...7f3c", never the key); BYOK requires a configured
  `DRIVERDNA_SESSION_SECRET` and returns a directive 400 when absent rather
  than silently deriving an insecure key. `ui/api.py`'s chat-session
  creation resolves the caller's own decrypted key before falling back to
  the server env key; a stored key that fails to decrypt (a rotated
  secret) logs a warning and falls back rather than hard-failing the
  session.
- `tests/test_keystore.py` (round-trip, wrong-secret failure, ciphertext
  never contains the plaintext, nonce is fresh every call) and
  `tests/test_byok_api.py` (real two-user login via the actual auth flow,
  not mocked: one account's key is invisible to another's GET, each sets
  independently, deleting one doesn't touch the other, the raw ciphertext
  column never contains the plaintext, unauthenticated access is 401 like
  every other route per the existing route-enumeration done-criterion).
- SPA: a "Your own AI keys" panel on `#/config`, one row per provider,
  `type="password"` input, a fingerprint + link to get a free key, never a
  plaintext readout. One real bug the render-parity crawler caught and
  this fixed properly rather than working around: the config panel's
  generic value renderer applied the `.num` (traceable-measurement) CSS
  class to every config value regardless of type, and the new
  `gemini-3.5-flash` string value contains a decimal-shaped substring
  ("3.5") that the crawler correctly flagged as an uncited number — fixed
  by only applying `.num` to values that are actually numbers, which was
  the correct rule all along and had just never been tested by a string
  value that happened to look numeric.

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

**BYOK (Track C2, SPEC.md A35)**: when an account has set its own key, that
account's coach/chat calls run against Google's free tier under *that
key's own* project — the same data-exposure tradeoff above applies, just
billed and rate-limited against the user's own quota rather than the
server's. The key itself never leaves the server once set (encrypted at
rest, decrypted only in-process to make the call) and is never included in
the payload sent to Google.

---

# Track M — Mobile (U5)

> **2026-07-29 update:** this track is absorbed into `docs/UI-SPEC.md`'s
> **U7** milestone (renamed from "U5" here to stop colliding with UI-SPEC's
> own U5, the pit-wall restyle), merged with the "design language v3" UI
> pass into one build because both touch the same CSS and views. Design
> below is unchanged and remains the source of truth for the mobile/PWA
> work; `docs/UI-V3-PLAN.md` Track A5 schedules it.

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
8. **`/openapi.json` had to be re-declared to be guarded at all** — and this
   one was a real hole, found by curling a live server rather than by the
   tests. FastAPI registers its schema with `add_route`, not
   `add_api_route`, so app-level dependencies never see it: with a
   passphrase set it still answered **200**, publishing every endpoint and
   request model. The `/api/`-prefixed route enumeration in the
   done-criterion did not look at it either, which is the more useful
   lesson — *a guard proven only against the paths you thought to list is
   not proven.* Fixed by `openapi_url=None` plus an ordinary `@app.get`
   route the guard does see; the enumeration test now walks **every** route
   the app declares, not just the `/api/` ones. With no passphrase
   configured the schema stays available exactly as before.

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
