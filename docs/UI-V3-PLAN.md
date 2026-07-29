# DriverDNA — UI v3, Incidents-for-newcomers, and the Gemini coach

**Status: plan adopted 2026-07-29 (owner-directed), not built.** Written for
execution by any agent — the next hands on this are expected to be Gemini CLI.
Branch of record for the work: `claude/ui-incidents-gemini-coach-93l5h7`.

**Where this sits.** It does not override `docs/SPEC.md` (engine),
`docs/ARCHITECTURE_VISION.md` (constitution), `docs/UI-SPEC.md` (interface) or
`AGENTS.md` (build rules) — where they conflict with anything below, they win
until the amendments in the next-but-one section are actually written. It
*builds on* two already-adopted designs in `docs/DEPLOY-SPEC.md`: **Track P**
(provider abstraction + Gemini) and **Track M** (mobile / PWA). Those are not
redesigned here; they are scheduled and extended.

---

## Context

Three owner-directed changes, in one plan because they overlap:

1. **The UI isn't fun to engage with.** The v2 "pit wall" language (UI-SPEC
   §Design language v2, built 2026-07-22) is correct and joyless: buttons with no
   press feel, one narrow column of stacked panels, every number shown flat with
   no way to ask *how was that computed*, and no view of progress over time. Owner
   wants: buttons/menus that feel good, the same palette plus fun accents, better
   use of space, complicated numbers collapsible behind an arrow that explains the
   methodology, and a manipulable line graph of scores over time.
2. **Incidents are engineer-facing.** The engine detects and classifies spins/offs
   and already maps each classification to exactly one coaching principle — and
   the UI renders none of that, just `trail brake oversteer · high · peak yaw 0.98
   rad/s`. A newcomer learns nothing. Owner wants: understand *why*, feel
   acknowledged, get told what to practise.
3. **Move the AI coach to Gemini**, with users spending their own Gemini usage.

A fourth, owner-stated constraint: **mobile still has to ship**, and the owner
expects to run out of tokens within a session or two. Track M (mobile/PWA) and
the v3 redesign touch the same CSS and the same views — building them separately
means doing the layout work twice, so this plan merges them.

---

## What is already true (do not re-derive)

- **The provider seam is clean and already specced.** `docs/DEPLOY-SPEC.md`
  **Track P** is an adopted design for exactly this Gemini swap (config key,
  `GeminiCoachProvider`, `GeminiChatProvider` transcript translation, tool-schema
  translation, 429 handling, `provider` provenance column, packaging extras).
  Track C below **builds Track P as written** and adds only the BYOK layer.
- **Track M (mobile/PWA) is likewise an adopted design.** Reuse it; Track A folds
  it in. Note the naming collision: DEPLOY-SPEC calls the mobile track "U5",
  which UI-SPEC already uses for the pit-wall restyle. Rename it **U7** on sight.
- **Incidents are already grounded end to end.**
  `report/payload.py:incidents_section` already attaches `coaching_principle_id`
  per event via `incidents/coaching.py`. The payload has the data; the UI
  (`ui/src/views/cohort.jsx`, the `p.incidents` block) never renders it. Track B
  is mostly a rendering + engine-text job.
- **`_bucket_score` already exists** (`model/scoring.py`) — a fundamental's score
  over an arbitrary `lap_pks` set, the machinery `trend` uses. The score-over-time
  series is a generalisation of it, not new maths.
- **The cache guards are already correct.** Every cached branch in
  `_adherence_component` / `_opportunity_component` / `_consistency_component` is
  gated on `and lap_pks is None`, so a bucketed score always re-queries. There is
  no silent-wrong-bucket bug today — but it means bucket scoring is entirely
  uncached, which Track A4 must fix carefully.
- **DEPLOY-SPEC is partly stale**: it assumes single-tenant and an Oracle VM.
  Reality (per `docs/STATUS.md`) is multi-tenant (SPEC.md A32) on Cloud Run.
  Where they conflict, STATUS.md wins; note the drift rather than silently
  following the stale text.

---

## Owner decisions made 2026-07-29 (record these before building)

**D1 — Gemini identity: BYOK plus a server fallback.** Investigated first,
because the literal ask ("users logged into their own Google accounts use their
own Gemini usage") is not available to third-party apps:

- Google AI Pro / Ultra are **chat subscriptions with no API access**.
- Gemini API quota and billing follow **the Google Cloud project behind the key**,
  never the signed-in end user.
- Google explicitly states that using third-party tooling to piggyback Gemini
  CLI's OAuth to reach its backend services is a **terms violation and grounds
  for account suspension**, and that the supported path for a third-party tool is
  an AI Studio or Vertex AI API key.
- OAuth against `generativelanguage.googleapis.com` does exist (`cloud-platform`,
  `generative-language.retriever`) but bills the project named by
  `x-goog-user-project` — so it would require every user to create a GCP project,
  enable the API, and attach billing. Rejected on UX.

So "their own usage" is delivered as **bring-your-own-key**: a user pastes their
own free AI Studio key; DriverDNA uses it for that user's coach/chat calls, and
falls back to a server-wide `GEMINI_API_KEY` when they haven't set one.

**D2 — the chart plots Driver Model fundamental scores only** (not per-lap
metrics). This is also why the chart is honest as a single overlay: all seven
series share one 0–100 score axis, so nothing is normalised and nothing is
blended.

**D3 — sequencing: Track A (UI v3 + mobile) first**, then B, then C. If tokens
run out mid-plan, each track's sub-steps are independently shippable and each
ends green.

---

## Step 0 — before touching anything

1. `git pull`; read `AGENTS.md` in full.
2. `git log --oneline -20`; skim `docs/STATUS.md` "Verified counts" and
   `CLAUDE.md` "Current status".
3. `python3 -m pytest` — **establish a baseline and read the output.** If `main`
   is already red, fix that before starting. Do not later report green without
   having known where you started. Known: `tests/test_render_parity.py` and
   `tests/test_offline.py` skip without Chromium/a built SPA; they are the
   owner's to run locally and CI does not cover them.

---

## Amendments to write FIRST (decision discipline, `AGENTS.md`)

Nothing in Tracks A–C builds until these are written, because each later step
cites them. Add to `docs/SPEC.md`'s amendment log (last entry is **A32**) and
mirror the design detail into `docs/UI-SPEC.md` / `docs/DEPLOY-SPEC.md`.

**A33 — Design language v3 ("cockpit feel").** A presentation amendment to
UI-SPEC's v2 section, which currently declares all eleven token colours and the
motion rule untouched. v3 changes four things and nothing else:

- *Palette*: new **chrome-only** accent tokens may be added. The three colour
  grammar rules stand verbatim — semantic colours (purple/green/amber/red) keep
  their exclusive meanings, red still never means driver pace, source identity
  stays structural. **A new accent may never encode a measurement**: it is legal
  on the wordmark, active-tab underline, hover/press states, disclosure chevrons,
  empty-state ribbons; illegal on any figure, bar, chart series, tile value, or
  finding row. Pick the hue from the two free regions (cyan ~185°, magenta ~325°)
  — every other hue is taken — and prove it in the mockup before adopting.
- *Motion*: v2's "≤150 ms, functional only" extends to **interactive-feedback
  micro-motion ≤180 ms** (press, hover, disclosure open/close, tab underline).
  Still no data-entrance animation, no chart animation, and
  `prefers-reduced-motion` still fully honoured.
- *Copy*: two new registers, each tightly bounded. A **methodology register**
  (explanatory prose, allowed *only inside a collapsed disclosure*) and a
  **newcomer register** (one short empathetic line, incidents only, inside the
  disclosure, never attached to a number). v2's "labels not paragraphs" rule
  continues to bind everything on the default render.
- *Progressive disclosure is not suppression.* Binding: the headline number, its
  `n`, and any `gate_reason` stay visible **uncollapsed**. Only derivation detail
  and methodology may collapse. Default-collapsed is allowed; the control must be
  visible, keyboard-reachable, and labelled. Nothing about UI-SPEC decision 7
  (suppression is visible, with its reason and progress) changes.

**A34 — score history (`dm-hist-v1`).** A new deterministic engine output: each
fundamental's own score over N contiguous date-ordered buckets of the driver's
dated laps, from the same `_bucket_score` machinery `trend` already uses. It
**produces no new kind of number** — no formula changes, no weights move, so
`dm-v2` is *not* bumped. Carries verbatim the two limitations `_trend` already
documents (era-relative opportunity baseline; cross-cohort bucket composition),
because a chart makes them more visible, not less true. Binding: **a bucket with
no scorable evidence is a null with a stated reason and renders as a gap — never
interpolated, and no line is drawn across it.**

**A35 — per-user AI keys (BYOK).** Reverses two written rules, by owner decision
(D1), and must say so rather than eliding it:

- `AGENTS.md` non-negotiable *"secrets are env-only: never persisted, printed, or
  logged"* → **refined**: a *user-supplied provider key* may be persisted,
  encrypted at rest, scoped to one account. Every server-side secret
  (`GARAGE61_TOKEN`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
  `DRIVERDNA_DATABASE_URL`, `DRIVERDNA_SESSION_SECRET`) stays env-only,
  unchanged. Never printed, never logged, never returned by any endpoint.
- UI-SPEC U6 condition 4 *"secrets never transit the browser"* → **narrowed**:
  that rule was written about `GARAGE61_TOKEN` — a server-side credential the UI
  must never ask for — and it stands for every server-side secret. A *user's own*
  provider key is by definition supplied by that user and can only arrive through
  their browser, over HTTPS, once, write-only. It is never sent back.

---

## Track A — UI v3: fun + mobile (do this first)

Milestone name: **U7** in UI-SPEC (absorbing DEPLOY-SPEC Track M).

### A1 — tokens and CSS foundation

Files: `ui/tokens.json`, `ui/src/main.jsx`, `ui/src/app.css`,
`src/driverdna/report/builder.py`.

- Add to `tokens.json`: the chrome accent(s) under `color`, plus new top-level
  `motion` (`fast`, `base`) and `space` groups. `main.jsx` already injects every
  token group generically — no change needed there.
- **`report/builder.py`'s `_TOKENS` mirrors the `color` + `font` groups only, and
  a test asserts it byte-for-byte.** A new colour key must be added there in the
  same commit or the suite goes red. `motion`/`space` follow `shape`'s precedent
  (SPA-only, not mirrored).
- Button feel (`.btn`, `.btn-primary`, `.btn.small`, `.btn.confirm`): `:active`
  press displacement, hover lift, ≤180 ms transitions. **Keep** the chamfer
  `clip-path` and the inset focus ring — `clip-path` clips outlines, so the inset
  ring is the visible-focus floor and is non-negotiable.
- Tab bar: animated underline (transform, ≤180 ms), scroll-snap at narrow widths.
  No hamburger — UI-SPEC is explicit that hiding where you are is the wrong trade.
- New `.disclosure` component built on native `<details>/<summary>` (free
  keyboard and screen-reader behaviour), chevron rotation ≤180 ms.
- Responsive pass (DEPLOY-SPEC Track M item 1, verbatim): fluid root padding via
  `clamp()`, single-column below ~48 rem, `.lossrow` and other fixed-column grids
  stack, tap targets ≥44 px everywhere including the chat input, wide tables keep
  their own `overflow-x` container so the body never scrolls sideways,
  `env(safe-area-inset-*)` respected.

### A2 — use of space

`#root` is `max-width: 64rem` with every panel stacked full-width. On ≥64 rem:
driver home puts tiles + rollup + sync into a two-column grid; the cohort view
puts the track map beside the findings column instead of above it. Below 48 rem
everything stacks. No view logic changes — CSS grid and container queries only.

### A3 — the methodology disclosure ("click the arrow")

**Text lives in the engine, not in JSX**, so the SPA and the static HTML reports
say the same thing and there is one place to correct it.

- New `src/driverdna/explain.py`: `METHODOLOGY: dict[str, str]` (id →
  plain-language paragraph) and `explain(id)`. Versioned static data, exactly
  like `coaching/ontology.py` — adding an explanation is a reviewable data
  change.
- **Reuse what already exists; `explain.py` fills only the gaps.** Already in the
  payload: `metric_definitions` (unit + description), `describe_key` (config
  docs), `PRINCIPLES[*].driving_principle`, `driver_model.note`,
  `incidents.note`, `Belief.insufficient_reason`, `finding.gate_reason`.
- Gaps to write: each of the three sources; median-of-top-3 vs single-best
  baselines; spread; outlier screening; cumulative loss; each confidence gate;
  the Driver Model's adherence / opportunity / consistency components;
  confidence; trend; evidence count; each incident classification.
- New read endpoint `GET /api/explain` — a static dict, pass-through, no
  computation in `api.py`.
- SPA: `<Methodology id="..."/>` in `ui/src/views/shared.jsx`, placed on every
  panel that shows a derived figure.
- Test `tests/test_explain.py`: assert the endpoint's key set matches a frozen
  list, **and** scan `ui/src/**/*.jsx` for `<Methodology id="...">` occurrences
  and assert every id referenced exists. Cheap, mechanical, catches drift.
- **Crawler note:** `page.eval_on_selector_all('.num', …)` reads `textContent`
  regardless of visibility, so numbers inside a *collapsed* disclosure are still
  crawled and must still trace to the payload. This is correct — do not try to
  exempt them.

### A4 — score-over-time chart (D2: Driver Model scores only)

**Engine** — new `src/driverdna/model/history.py`:

```
score_history(db, *, driver, config) -> {
  "series_version": "dm-hist-v1",
  "scoring_model_version": SCORING_MODEL_VERSION,
  "x_axis": {"kind": "date_bucket" | "unavailable",
             "labels": [...], "bucket_lap_counts": [...]},
  "series": {fundamental_id: {"signal_status": ..., "points": [
              {"x": i, "score": float|null, "n": int, "reason": str|null}]}},
  "caveats": [...]   # the two _trend already documents, verbatim
}
```

- Bucketing: `db.dated_self_lap_pks(driver)` → `config.model.history_buckets`
  (new key, default 6) contiguous equal-count buckets, ordered by
  `(lap_date, lap_pk)` — **the exact ordering `_trend` uses.** Add a test that a
  2-bucket run reproduces `_trend`'s own two scores exactly; that is what proves
  the generalisation didn't drift.
- Each bucket's score via the existing `_bucket_score`. No new maths (A34).
- **Performance, and the one dangerous edit in this plan.** Bucketed scoring is
  currently uncached by construction (every cache branch is gated on
  `lap_pks is None`), so 6 buckets × 7 fundamentals re-queries per cohort every
  time. Fix by giving `_CohortCache` a `lap_pks` field, building one cache per
  bucket, and changing each guard from `lap_pks is None` to
  `cache.lap_pks == lap_pks`. **Required safety test:** for a synthetic DB with
  genuinely different evidence per bucket, the cached and uncached bucket scores
  must be identical, and two different buckets must produce different scores.
  Without that test a stale cache silently draws a flat line.
- Artifact: extend `model/report.py` so `driverdna model` prints the series;
  regenerate `docs/driver-model-report.md` from the real fixtures. Every
  milestone ends with its inspectable artifact regenerated.
- Endpoint `GET /api/driver/score-history` — pass-through.

**SPA** — a panel on `#/model`, not a new route. Two reasons: the six-tab shell
is a v2 invariant, and `#/model` is already in both the parity and offline route
lists, so the chart is covered by the existing gates with no route-list edit.

- Hand-rolled inline SVG, like `trackmap` and the Driver Model pyramid. **No
  chart library** — the same-origin/offline guarantee and the zero-external-asset
  rule.
- Interaction: one toggle chip per fundamental (multi-select, several series
  overlaid on the shared 0–100 axis); hover/tap a point reveals score + `n` +
  bucket label, all read straight from the endpoint; keyboard-navigable.
- **Never draw a line segment across a null point.** Render the gap and, on
  hover, the stated reason.
- Deliberately **not** a radar chart. Two reasons, and the second is the one
  people miss: its shaded area reads as an overall score that nobody computed and
  that cannot be decomposed to its sources (philosophy #4 / A14) — *and* that
  area is not even a well-defined statistic, since it changes when the spokes are
  reordered. Same reasoning that made the Driver Model tab a pyramid on
  2026-07-21. (`CLAUDE.md` cites "philosophy #6" for that earlier decision; the
  principle it actually rests on is **#4** — fix that citation when writing A33.)

**Two test-gate consequences, both easy to miss:**

1. `tests/test_render_parity.py:_number_pool()` builds its pool from a hardcoded
   list of endpoints. **Add `/api/driver/score-history` and `/api/explain` to it**
   or every chart figure fails the gate as an invented number.
2. The committed fixture manifest is deliberately undated, so
   `dated_self_lap_pks` is empty on the fixture DB and the chart will render its
   *unavailable* state in the browser gates. That is parity-clean by construction
   and is the right outcome — but it means **the populated chart path is not
   covered by the browser gate**. Cover it with a Python-level test that builds a
   synthetic dated DB. **Never edit `tests/fixtures/`** to make the browser test
   richer (`AGENTS.md`, absolute).

### A5 — mobile / PWA (DEPLOY-SPEC Track M items 3–5)

- `manifest.webmanifest` (standalone, dark `theme-color` read from
  `ui/tokens.json` — never a second hardcoded palette), maskable icons,
  `apple-touch-icon`, emitted by Vite into the in-package static dir. Node stays
  build-time only.
- Service worker, one binding rule: **cache the shell, never the numbers.**
  Hashed build assets precached; every `/api/*` response network-only. The API
  already sets `no-store` (landed with H1). Offline shows an explicit "not
  connected — no current data" state in the existing empty-state register. It
  never shows the last numbers it saw — a stale finding presented as current is
  the exact failure this product exists to prevent.
- HTTPS precondition is already met (Cloud Run).
- Verify the service-worker registration does not trip `tests/test_offline.py`.

### A6 — mockup and owner review

Produce `docs/ui-redesign-mockup-v3.html` with labelled placeholder numbers, as
v2 did, showing both candidate accent hues. Owner reviews before the restyle is
declared done.

### Track A done-criteria

- All five trust gates green (browser gates run locally; CI does not install
  Chromium).
- `_TOKENS` byte-match test green.
- Render-parity crawler passes **twice**: desktop, and a second pass at 390×844
  asserting no horizontal body overflow on any route.
- `driverdna model` artifact regenerated and reviewed.
- Built SPA reshipped in-package.
- Owner accepts the mockup, or amends UI-SPEC.

---

## Track B — incidents a newcomer can learn from

### B1 — surface what the engine already decided

`report/payload.py:incidents_section` already attaches `coaching_principle_id`.
Add to each event, from `coaching/ontology.py`: `coaching_expression`, `drill`,
`driving_principle` (the SPA cannot import the ontology, so it must come through
the payload).

Add to `explain.py`, keyed by classification: `plain_what`, `plain_why`,
`what_to_practise`, and the **one** newcomer-register line (A33). Deterministic
static text — works offline, with no API key, and cannot fail a validator.

New `IncidentCard` in `ui/src/views/shared.jsx`, replacing the raw block in
`cohort.jsx`:

- **Visible by default:** what happened in plain language, the corner (linked),
  the mechanism, and the N=1 line from the payload's own `note`.
- **Behind the disclosure:** the empathetic line, the mechanism explanation, the
  drill, and the raw evidence (`min_speed_kmh`, `peak_yaw_rate`, and
  `detail.brake_at_onset` / `throttle_at_onset` / `throttle_before` /
  `steer_mag_deg_at_onset`). This is exactly the "hide complicated numbers, arrow
  explains the methodology" pattern from Track A3.
- **`unclassified` / `external`: no cause, no principle, no drill, no guess.**
  Binding — `incidents/coaching.py` deliberately maps them to nothing, and the UI
  must not paper over it. Render "the trace didn't say clearly enough" plus a
  driver-runnable self-check.

### B2 — mechanism counts (optional, cheap)

A per-cohort tally by classification. **Counting, not computing** — the same
precedent as the existing `shownCount`. Label it as a count of events and keep
the never-a-trait line adjacent. A *pattern* claim would need N and the normal
gates; do not make one here.

### B3 — let chat see incidents (lifts the M5 boundary)

Today `chat/session.py:build_chat_bundle` strips `incidents` deliberately, so a
driver cannot ask "why did I spin at C14?". Lift it:

- Stop stripping the section; add incident IDs to `ChatSession._known_ids`.
- Bump `CHAT_PROMPT_VERSION` `chat-v2` → `chat-v3`.
- Add a read-only `get_incident` tool in `chat/tools.py`.
- Extend `CHAT_SYSTEM_PROMPT` with the coach's existing incident rule verbatim:
  the AI explains the engine's classification and may never pick, override, or
  invent one; an incident with a null `coaching_principle_id` cannot be explained
  at all.

> **This edits the grounding validator's universe, which `AGENTS.md` names the
> highest-risk change in the repository.** The change must be strictly additive —
> new IDs become citable; no existing rejection is loosened. Add a test proving a
> reply citing an unknown incident ID is still rejected, and one proving a reply
> explaining an `unclassified` incident is rejected.

### B4 — artifact

Regenerate `docs/incidents-report.md` via `driverdna incidents`.

### Track B done-criteria

- The two real fixture incidents (`9XVJTW` trail-brake spin, `9PH9M2` dead stop)
  render as newcomer-legible cards, verified in the browser.
- The `unclassified` fixture incident (`5ZBWTZ` C01) shows no guessed cause.
- Chat incident tests green, including both rejection tests above.
- Suite green; no existing test weakened.

---

## Track C — Gemini coach with bring-your-own-key

### C1 — build DEPLOY-SPEC Track P exactly as adopted

Items P1.1–P1.7, unchanged: `coach.provider` config split; `GeminiCoachProvider`
(`coach/provider.py`); `GeminiChatProvider` (`chat/session.py`) translating the
Anthropic-shaped transcript inside the provider rather than refactoring
`_messages`; tool-schema translation as a real tested function that **raises on
any schema keyword it cannot faithfully translate** (a silently dropped
`required` is exactly the quiet degradation this project forbids); bounded
backoff on 429 with an explicit "rate limited" error — **never an empty reply**,
which would enter the validator and be rejected as a grounding failure, blaming
the wrong component; a migration adding `coach_outputs.provider TEXT NOT NULL
DEFAULT 'claude'` (honest — every existing row was Claude), surfaced in
`driverdna history`; and `anthropic` moving out of hard dependencies into
`ai-claude` / `ai-gemini` extras.

**Do not pin a Gemini model name from memory.** Read the current model list off
`ai.google.dev/gemini-api/docs/pricing` at build time and record the pinned name
plus the date it was verified — DEPLOY-SPEC's own standing rule, and A28's
standing lesson about inference presented as fact.

### C2 — the BYOK layer (new; A35)

- Migration: `user_api_keys` (`owner_user_pk`, `provider`, `ciphertext`, `nonce`,
  `fingerprint`, `created_at`), unique on (`owner_user_pk`, `provider`).
- Encryption: **AES-GCM via `cryptography`**, key-encryption key derived from the
  existing `DRIVERDNA_SESSION_SECRET` with `hashlib.scrypt` (the same primitive
  `auth.py` already uses for passwords). `cryptography` is currently only a
  transitive install, so **declare it explicitly** in the `ui` extra. This is a
  deliberate deviation from the project's no-new-dependency instinct: that
  instinct exists to keep vendor SDKs out of paths stdlib handles well, and
  stdlib ships no AEAD. Hand-rolling encryption here would be strictly worse.
  Record the reasoning in the amendment.
- Endpoints: `PUT /api/settings/ai-key` (write-only), `GET /api/settings/ai-key`
  → `{configured, provider, fingerprint: "AIza…7f3c", set_at}` and **never the
  key**, `DELETE /api/settings/ai-key`.
- `make_chat_provider` (and the coach's equivalent) become per-user: the caller's
  own key if set → else the server `GEMINI_API_KEY` → else a directive error
  state naming what to do. Never read a key from the request body at call time;
  only the dedicated settings endpoint accepts one.
- UI: a panel on `#/config`. `type="password"` input, a fingerprint + "set on
  <date>" readout, a delete control, and a plain link to `ai.google.dev` for a
  free key. An anchor is fine for the offline gate — that gate blocks *requests*,
  not hrefs; just ensure nothing prefetches it.
- Tests: never a live call and never a real secret. Assert the key never appears
  in any response body or log line, that `GET` returns only the fingerprint, and
  that a user cannot read another user's key (the `owner_user_pk` isolation the
  A32 work already tests elsewhere).

### C3 — the acceptance gate that matters

DEPLOY-SPEC's own criterion, kept: a **live run** with a real `GEMINI_API_KEY` —
`driverdna coach` on the real fixture cohort, output passing the strict validator
**unmodified**. Record the observed rejection/regeneration rate in
`docs/STATUS.md`. If the free-tier model routinely needs the second attempt, say
so plainly. **Never tune the validator to accept a weaker model** — that inverts
the entire point of the grounding contract.

### Track C done-criteria

- Every existing coach/chat test passes unchanged against the mocked provider —
  the mechanical proof the seam moved nothing.
- `GeminiChatProvider` unit test drives a mocked Gemini-shaped response through
  the translation both ways, including a two-tool-call turn and a tool-result
  round trip.
- Live coach run passes the validator; rate recorded.
- Suite still runs with no secrets, no server, no container.

---

## Guardrails (binding — from `AGENTS.md`)

- **Never weaken, delete, `skip`, `xfail`, or narrow an existing test to reach
  green.** A failing test is a finding: record it and say so.
- **Never edit anything under `tests/fixtures/`.** Those are real recorded laps
  and the A18 blind-acceptance anchor. Change the code to fit the evidence.
- **The UI never computes a measurement.** Every on-screen number must exist in
  the payload or a read endpoint. Layout math only.
- Changing a number the engine produces is a spec-level change: a SPEC.md
  amendment, plus a model-version bump if a formula or weight moves. A34 is
  explicit that the score history moves neither.
- The grounding validator (`coach/`, `chat/`) is the highest-risk edit here.
  Additive only.
- TDD: Red → Green → Refactor. Never modify a test file during the Green step.
- Commit trailers on every commit (`Agent:` + `Co-Authored-By:`); the branch of
  record is `claude/ui-incidents-gemini-coach-93l5h7`.
- End of session: update `docs/STATUS.md`'s dated snapshot and record every
  decision in the SPEC amendment log and/or PROJECT-BRIEF's decision log.

---

## Verification

Per track, in order:

1. `python3 -m pytest` — full suite, both backends where a local Postgres is
   configured (`DRIVERDNA_TEST_DATABASE_URL`).
2. `cd ui && npm run build` — reships the SPA into `src/driverdna/ui/static/`.
   Commit the built assets, as previous milestones did.
3. **Browser trust gates, locally** (CI does not install Chromium, so green CI is
   *not* proof these hold — say so rather than implying coverage):
   `python3 -m pytest tests/test_render_parity.py tests/test_offline.py
   tests/test_cockpit_ui.py tests/test_auth_ui.py`
4. Determinism, unchanged and mechanical: import the fixtures twice into separate
   DBs and byte-diff the normalized JSON/Markdown/HTML reports.
5. Regenerate and review the artifacts touched: `driverdna model`
   (`docs/driver-model-report.md`), `driverdna incidents`
   (`docs/incidents-report.md`).
6. Track C only: the live Gemini coach run (C3), against the real fixture cohort.
7. Owner review of `docs/ui-redesign-mockup-v3.html` and the built SPA on a phone
   — install to home screen, open offline, confirm it says "no current data" and
   shows no stale figures.

---

## Sequencing and budget

**A1 → A2 → A3 → A4 → A5 → A6**, then **B1 → B2 → B3 → B4**, then
**C1 → C2 → C3**. Each numbered step ends with the suite green and is
independently shippable, so running out of tokens mid-plan leaves a working tool
rather than a half-restyled one.

Cheapest-per-token if the budget collapses: **B1** (the payload already carries
everything; it is a rendering + text pass) and **A1** (tokens + button/press feel
+ responsive CSS, no view logic). Most expensive: **A4** (new engine module,
cache edit, two test-gate consequences) and **C1** (transcript and tool-schema
translation).
