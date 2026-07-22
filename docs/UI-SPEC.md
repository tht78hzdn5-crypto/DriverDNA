# DriverDNA — UI Layer Spec (`docs/UI-SPEC.md`)

Amends `docs/SPEC.md`, which remains authoritative for the engine; add one line there referencing this document. The nine philosophy points bind every screen. The governing rule is SPEC philosophy #2 restated for rendering: **the UI renders what the engine computed and never computes a measurement.** Every number on screen must exist verbatim in the JSON report payload or a DB read endpoint. The self-contained static HTML reports remain unchanged as the zero-infrastructure fallback.

## Intent

A local cockpit for one driver. Its personality is the philosophy made visible: evidence is one tap away from every number, the three sources are never blended, and what the tool *isn't* saying — and why — is displayed with the same care as what it is. For the first weeks of real use, gates will suppress most findings; the empty state is therefore a primary state, designed as direction ("1 of 2 sessions toward this gate"), not apology.

## Decisions of record

1. Shape: a thin FastAPI service plus a React (Vite) single-page app, launched together by `driverdna ui`, bound to `127.0.0.1` only. Browser is the shell; a Tauri desktop wrapper is deferred until wanted, and nothing may depend on one.
2. The normalized JSON report payload is the rendering contract. The API's payload endpoints are pass-throughs over `build_cohort_payload` / `build_driver_payload`; the SPA performs no aggregation, rounding-into-new-values, re-ranking, or client-side statistics — layout math only.
3. Writes exist solely as wrappers over existing audited paths: `db.annotate_finding`, `ConfigStore.propose`/`apply`, `ChatSession`. The API layer contains no business logic; a write endpoint's test asserts its DB and audit effects are identical to the equivalent CLI action.
4. Chat renders no unvalidated text. `ChatSession` responses are mechanically validated before display, so there is no token streaming; SSE carries progress states (thinking → consulting tools → validating) and a visible audit of read-only tool calls ("consulted: F12, C03 brake-release distribution"), then the validated response arrives whole. A rejected-then-failed response surfaces as an error card, never as retracted text.
5. Confirm is always a distinct, explicit, non-default action. Staged config proposals live server-side (`ChatSession.staged` / `ConfigStore.propose`); the UI reflects that state, survives refresh, and renders current → proposed values plus the re-flag preview before the confirm control.
6. The three source tags (`vs-principle`, `vs-self`, `vs-reference`) render as three visually distinct sections with their own treatments; reference sections carry the "gap" label inline. No screen contains a blended score, letter grade, progress ring, or any synthesized "overall" figure.
7. Suppression is visible. Gated findings appear in place with their stated reason and live progress toward the gate (counts from the DB, which is counting, not computing findings). Annotated findings move to their own visible group with the measurement still shown; nothing is silently hidden.
8. Fully offline: all assets (fonts, chart code) bundled at build time; no CDN, no external requests. Node is a build-time dependency only — the built SPA ships in the package's static directory and `driverdna ui` needs Python alone at runtime.

## API surface

Read (all pass-through or existing read paths):
`GET /api/driver` (rollup payload) · `GET /api/cohorts` · `GET /api/cohorts/{id}/payload` · `GET /api/cohorts/{id}/corners` (identity map incl. apex GPS + class) · `GET /api/laps?cohort=` (metadata, session key, quality flags) · `GET /api/metrics/{corner_id}/{metric}/distribution` (mirrors the chat read-only tool) · `GET /api/config` (`config_snapshot` + `describe_key`) · `GET /api/config/history`.

Write (wrappers only, each returning the audit record it created):
`POST /api/findings/{id}/annotate` · `POST /api/config/propose` · `POST /api/config/apply` · `POST /api/chat/sessions` · `POST /api/chat/sessions/{id}/messages` (response via SSE per decision 4) · `POST /api/chat/sessions/{id}/confirm/{n}` · `POST /api/laps/upload` (multipart; wraps `import_lap_file`, the same function `driverdna import` calls per file — the one endpoint deliberately allowed to create the DB fresh, since it's the cold-start path; car/track optional — auto-detected per file from the newer Garage61 filename shape when omitted).

## Views

1. **Driver home.** Cumulative seconds lost by technique (the product's headline claim), per-class breakdown, session trend, and the gates panel: every suppressed rollup with reason and progress. If nothing clears the gates yet, this page *is* the gates panel plus what to do next.
2. **Cohort (car + track).** The signature element: a track outline drawn from a representative retained lap's `Lat`/`Lon` trace, with corner markers at the frozen apex-cluster positions, colored by attributed cumulative loss and badged by class — the instrument rendering the driver's actual data, not a stock map. This is the one bold element in the product; everything around it stays quiet. Beside it, findings in three source sections, and the corner list.
3. **Corner drill.** Phase deltas vs the labeled baselines (median-of-top-3 primary, single-best labeled, reference gap when present), metric distributions, lap-over-lap trend, landmarks over the canonical window. All series straight from payload or the distribution endpoint.
4. **Finding detail.** The evidence view: N, spread, source tag, confidence context, evidence IDs resolving to real laps and corners (deep-linked), plain-language principle rationale where applicable, and the annotate actions (acknowledged / intentional) with their effect stated before use.
5. **Chat.** Grounded session per decision 4/5. Evidence IDs in responses are links into views 3–4. Staged proposals render as a distinct card; `Confirm change` is its own labeled action.
6. **Config.** Snapshot with per-key documentation, edits flowing through propose/apply, and `config_history` as the audit view with revert.
7. **Laps.** Import/session listing with quality flags surfaced (clipped pedals, GPS-degraded, outlier screens) — the data-quality conscience of the instrument. **Import itself is `#/upload` (built 2026-07-21)**: file picker, car/track/role/date/session fields, and the engine's own per-file report (matched corners, admitted, class changes, duplicate detection) rendered back verbatim — no CLI required, including for the very first lap ever imported. Car/track are optional: left blank, each file's own car/track is auto-detected from the newer Garage61 export filename shape (`docs/garage61-api.md`), each file landing in its own resolved cohort; a file that can't be resolved either way is rejected up front, listed by name.
8. **Garage (v2, 2026-07-22 — specced, builds with U5).** The cohort index as its own destination: a card grid over the existing `GET /api/cohorts` (car @ track, driver), click-through to each cohort. Driver home stops doubling as the cohort list and becomes purely the rollup (see "Design language v2"). No new endpoint; render-parity-clean by construction.

## Design language and tokens

This section is the visual source of truth for both surfaces: the SPA and the static HTML report templates, which are brought onto the same tokens during U4 so the product has one appearance. Tokens live in a single file (`ui/tokens.json`) consumed by both.

Ground it in the subject: this is a measurement instrument for motorsport, and the sport already has a visual language — timing screens and telemetry software. The palette adopts that vernacular rather than inventing one, so it reads instantly to a racer.

**Color grammar — three rules governing every screen:**

1. Color encodes measurement semantics only, per international timing convention: purple = best (fastest execution, session best); green = at or under baseline; amber = off pace / attention; red = data-quality problems and errors **only, never driver pace** — the instrument does not editorialize about driving with alarm color.
2. The three source tags are differentiated structurally — labeled eyebrows, distinct left-rule styles, tag chips — never by the semantic colors above, so a section's identity can never be mistaken for a verdict.
3. Interaction (links, focus, selection) uses one quiet accent distinct from every semantic color, so nothing interactive masquerades as data.

**Tokens (defaults; tunable in one place):** ground in layered dark neutrals — base `#101318`, panel `#171B22`, raised `#1F242D`, line `#2A303A`; text `#E8EAED` primary / `#8C93A0` dim. Semantic: purple `#B48CFF`, green `#3ECF8E`, amber `#E8A13C`, red `#E5484D`. Interactive accent: muted steel `#6EA8D8`, used sparingly. Dark-only in v1; the token layer keeps a light theme possible, not promised.

**Typography:** every figure set in a monospaced face with tabular numerals (IBM Plex Mono, bundled) — a number is never proportional; UI text in a neutral grotesk (IBM Plex Sans, bundled); no decorative display face *(amended by v2, 2026-07-22: one functional condensed display face for structure labels only — see "Design language v2"; body text and data remain Sans/Mono only, so the original intent, no typographic editorializing about numbers, survives verbatim)*. Data tables run timing-screen dense; interactive controls keep full hit areas.

**Motion:** functional only — state transitions ≤ 150 ms, no chart entrance animation, `prefers-reduced-motion` honored.

**States:** gated/suppressed items keep full structure at reduced emphasis with their reason line — legible, never faded to invisibility. Annotated findings sit in their own labeled group, measurement visible. A staged config proposal renders as an amber-ruled card (attention semantics) until confirmed or discarded.

**Copy:** the product's fixed vocabulary — findings, gates, evidence, sources, staged, confirmed — one name per concept everywhere. Errors and empty states give direction, not mood. Quality floor without announcement: visible keyboard focus, readable at laptop and phone widths.

## Design language v2 — "pit wall" (owner-directed, 2026-07-22)

Owner directive: keep the palette; add simplicity, more buttons, and a small
tinge of personality; the reference register is iRacing's UI and promotional
language. v2 is a **presentation amendment**: the section above remains the
base grammar and stays binding except where this section explicitly amends
it. Mockup with labeled placeholder numbers: `docs/ui-redesign-mockup.html`.

**Untouched, stated so nobody re-litigates it:** all eleven color values in
`ui/tokens.json`; the three color-grammar rules (purple/green/amber
semantics, red never driver pace; source identity structural, never color;
one quiet interaction accent); mono tabular numerals for every figure;
suppression/annotation rendering; motion rules; table density; dark-only;
all five trust gates; the static reports' current appearance (reports
inherit token *additions* through the `_TOKENS` mirror test but are not
restyled this pass).

**Type ramp (the personality core; amends the base typography clause).**
One display face: **IBM Plex Sans Condensed** (self-hosted via
`@fontsource`, latin subset, weights 600/700 only — U4's subsetting
discipline), added to tokens as `font.display`. Used exclusively for
*structure labels*: wordmark, view titles, section headers, nav tabs,
button labels, stat-tile captions — always uppercase, `letter-spacing:
0.06em`. Never body text, never a measurement. Same Plex superfamily, so
the instrument still reads as one voice. (`font.display` lands in
`report/builder.py`'s `_TOKENS` mirror too — the byte-match test enforces
it; reports simply don't reference it yet.)

**Shape: the chamfer.** One rule: an emphasized element cuts its top-right
corner at 45° via `clip-path` — panels and stat tiles 10px, buttons 8px;
chips, inputs, and table cells stay rectangular. This is the single
iRacing-vernacular tell in the geometry; everything else stays
hairline-bordered and flat. Because `clip-path` clips outlines, chamfered
elements take keyboard focus as an **inset** ring (`box-shadow: inset 0 0 0
2px var(--accent)`) — the visible-focus floor is non-negotiable.

**Buttons ("more buttons", half one: prominence).** A real system, three
tiers plus the existing confirm:

- `btn-primary` — filled `--accent`, label ink is `--base` (reusing the
  base token; no new color), chamfered, display-face uppercase, min-height
  2.5rem. At most one per view section.
- `btn` (secondary) — the current quiet raised/bordered style, chamfered,
  display-face label.
- `btn small` — unchanged, for inline/dense contexts.
- `btn confirm` — unchanged green-outlined semantics; still never a default
  action, still visually distinct (decision 5).

Binding rule: **an action is a button; navigation to an entity is a link or
card.** Every control that currently renders an action as a text link
(import CTAs, "+ more principles", chat send, annotate/propose/apply/
revert) becomes a system button. Hit areas ≥ 2.5rem.

**Shell and navigation (simplicity, half one).** The topbar becomes a fixed
tab bar that never changes shape with context: wordmark left — `DRIVER DNA`
in the display face, `DNA` in `--accent`, beside an 18px inline-SVG mark
(two interleaved polylines: a DNA half-twist that reads equally as two
racing lines through a chicane; drawn once in the shell, zero image assets)
— then six constant tabs: **Driver · Model · Garage · Chat · Import ·
Config**. The active tab carries a 2px `--accent` underline, the one "kerb
stripe" in the chrome. Contextual jumps (a cohort's laps/chat) leave the
global nav and become a **context strip** under the view title: breadcrumb
plus secondary buttons scoped to the entity. Narrow widths: tabs scroll
horizontally; no hamburger.

**Stat tiles ("pit board").** Views open with a row of tiles: a large mono
figure (~1.6rem, tabular) over a display-face caption. Tile values come
only from the payload/read endpoints or are counts of rendered payload
items (the existing `shownCount` precedent — counting, never computing).
Driver home: cohorts · rollups shown · gated. Cohort: laps · sessions ·
findings shown · suppressed (promoting the existing chips). Corner drill:
the phase deltas vs baseline.

**Copy density (owner feedback 2026-07-22 on the first mockup: "very
wordy").** Binding for U5 and after: the instrument speaks in labels, not
paragraphs — the iRacing/timing-screen register. Rules: a caption or tile
label is ≤ 3 words; an empty/state line is one sentence, not two; the
explanatory sub-paragraphs that currently sit under headings (`.sub` blocks
on cohort, config, chat, upload, model) are cut to a single short line or
dropped — the philosophy is shown by structure (evidence one tap away,
sources separated), not narrated in prose every screen. Measurement copy
and gate reasons keep their exact words (accuracy over brevity there); this
trims *chrome*, never a number or a stated reason. When a longer
explanation is genuinely useful, it goes in a `title=` tooltip or the
finding/evidence view, not inline on every render.

**Personality (the "small tinge" — a bounded kit, not a license).** Exactly
four elements, plus a boundary:

1. The wordmark + helix/racing-line mark (above).
2. The kerb-stripe active-tab underline.
3. Empty states open with an 8px checkered ribbon (CSS
   `repeating-conic-gradient` in `--raised`/`--line` — dim, structural, no
   new color) above the existing direction-first copy, plus a real CTA
   button. Empty states remain a primary designed state.
4. Register: motorsport idiom is allowed in *state* copy only (empty,
   success, progress), at most one idiom per screen — "Nothing in the
   garage yet — bring your first laps in."; upload success: "In the
   garage." Never in measurement copy, gate reasons, or any sentence
   carrying a number.

Boundary (binding): **no license-class letter cosplay** on scores or
confidence — a letter on a score is a grade, an opaque blend by another
name; no alarm-red flourishes (color rule 1 stands); no decorative motion
(motion rules stand); no texture or carbon-fiber imagery (image assets stay
at zero).

**Tokens delta.** `font.display` (above) plus a new top-level `shape` group
(`chamfer`, `chamferSmall`) consumed by generalizing `main.jsx`'s injection
loop from color-only to every token group. `_TOKENS` mirrors the `color` +
`font` merges only, so `shape` never touches the reports; the
`font.display` addition does, one line, test-enforced.

**Reference-lap visibility (owner-directed 2026-07-22; folds REFERENCE-LAPS.md
R1 into this restyle).** Reference laps are a built, tested, isolated engine
feature (`docs/REFERENCE-LAPS.md`) that is invisible in the UI until fed and
unexplained once present. Because U5 already rebuilds the exact surfaces
involved — cohort stat tiles, empty states, the upload view — reference
visibility rides U5 rather than waiting:

- The **vs-reference source section** becomes a designed primary state at
  N=0 (like every other empty state here): a dim direction line — *"No
  reference laps yet. Add a faster driver's lap as a reference for gap
  context — it never enters your history, trends, or scores."* — plus a
  button to `#/upload`. This is the affordance that makes the feature
  discoverable at all; it needs no reference data.
- A **guarantee line** wherever references appear, stating the isolation in
  the product's fixed vocabulary (never history / trends / classes /
  consistency / incidents / Driver Model). The upload role select's existing
  one-line hint is promoted to the same visible copy.
- A **reference stat tile** in the cohort pit-board row ("N reference laps",
  counted from `/api/laps` rows — the counting precedent), each
  vs-reference finding's meta gains **"ref n=K"** (`details.reference_n`,
  already in the payload), and a compact **"References" line** names each
  reference's driver + lap time. Lap time is already returned by
  `/api/laps`; **driver is the one read-field addition** to that endpoint
  (`api.py`) so the name traces to a read endpoint — render parity honored,
  never bypassed.
- Color grammar unchanged: references stay structurally identified (the
  existing dotted `vs-reference` left-rule and tag chip), never a semantic
  color — a gap is context, not a verdict (color rule 2; SPEC.md
  decision 8).

The engine is untouched; this is pure rendering of values that already
exist (plus one read field). Full spec and the deeper R2/R3 work:
`docs/REFERENCE-LAPS.md`.

**Test consequences (stated here so no future view forgets):** the browser
trust-gate tests hardcode their route lists (`tests/test_render_parity.py`,
`tests/test_offline.py`) — new routes are never auto-covered. U5 adds
`#/garage` to both. Any DOM-structure assertions that key on restyled
markup are updated in the same change, never deleted. `#/garage` goes to
the offline route list only (it renders no measurement; the render-parity
gate requires a `.num` per route, so garage is excluded there exactly as
`#/upload` is). The shared `tests/fixtures/` DB is **not** given a
`role='reference'` lap — the reference figures are parity-clean by
construction (integer counts + pooled `/api/laps` lap times), and seeding
the shared fixture would perturb the determinism and report-snapshot tests.

## Milestones

- **U0 — API layer.** All endpoints above; contract tests: payload endpoints byte-identical to `driverdna report` JSON on a fixture DB; each write endpoint's effects identical to the CLI equivalent; nothing importable from the SPA to compute.
- **U1 — Read-only views.** Driver home, cohort (with track rendering), corner drill, finding detail, laps. Render-parity test: crawl every number in rendered output on the fixture DB and assert each exists in the payload/read endpoints.
- **U2 — Writes.** Annotations and config panel through the gated paths; audit visible in-UI.
- **U3 — Chat.** SSE progress, validated-only rendering, tool-call audit, staged/confirm flow end to end.
- **U4 — Packaging & polish. Done (2026-07-21).** `driverdna ui` command, built assets shipped in-package — already true since U0. This pass closed the remaining gaps: the static HTML report templates migrated onto `ui/tokens.json` (`report/builder.py`'s `_TOKENS`, kept in sync by a test that reads the real JSON file; chart colors mirror the SPA's own `app.css` convention exactly — neutral fill, single max value in `--warn`); fonts self-hosted in the SPA (`@fontsource`, latin subset, the weights actually used); and offline verification became a real dynamic test (trust gate 5) — Playwright actively blocking every non-localhost request across every route, not a static grep. Report HTML determinism (byte-identical across independent renders) is now its own test, closing a gap this milestone's own text named. A broader visual "design pass" beyond color/type/offline was not separately re-audited — U1–U3 already built the SPA against this document's rules directly.

- **U5 — "Pit wall" restyle (design language v2; specced 2026-07-22, not yet built).** Tokens delta + condensed display face self-hosted; shell/tab bar + wordmark; button system; stat tiles; Garage view (view 8); empty-state kit; **reference-lap visibility (REFERENCE-LAPS.md R1: the N=0 vs-reference direction state + button, the guarantee line, the reference stat tile, "ref n=K" on gap findings, and the "References" line over the one `/api/laps` driver-field addition)**; per-view application (home, cohort, corner, finding, laps, config, chat, upload). Done when: all five trust gates green; `_TOKENS` byte-match green; built SPA ships in-package; owner reviews the built result against `docs/ui-redesign-mockup.html` and accepts or amends here. **Built 2026-07-22** — see PROJECT-BRIEF.md. Two route-list details resolved at build time and flagged (not the "both lists" the plan first assumed): `#/garage` is added to the **offline** route list only — it renders no measurement, and the render-parity gate's own `wait_for_selector('.num')` requires one, so garage is excluded from that crawl for the same reason `#/upload` already is. The reference-visibility figures are parity-clean by construction (counts and `ref n=K` are integers, out of the fractional gate's scope; reference lap times trace to `/api/laps`, which the crawler already pools), so **no `role='reference'` lap is forced into the shared `tests/fixtures/` DB** — doing so would perturb unrelated determinism and report-snapshot tests; the crawler exercises the N=0 reference state, and the populated path shares the same pooled-endpoint reads.
- **U6 — Cockpit actions ("more buttons", half two; specced 2026-07-22, not yet built).** Two write endpoints wrapping existing audited paths under decision 3's discipline (effects identical to the CLI equivalent, tested): `POST /api/sync` (wraps `sync_driver`; `GARAGE61_TOKEN` stays env-only — an absent token is a directive error state, **never an input field**; secrets never transit the browser) and `POST /api/cohorts/{slug}/rebuild-map` (wraps the A22 in-place refreeze; behind its own explicit, distinct confirm control per decision 5, because it rewrites frozen geometry). Each button renders the engine's own result verbatim (sync counts; rebuild report including cleared-stale-phase notices). A button appears only when its endpoint exists — the UI never shows a dead control.

  **Conditions of done (all must hold; U6 begins only now that U5's gates pass — 2026-07-22):**
  1. `POST /api/sync` is a wrapper over `sync_driver(db, client, *, driver, config, car=None, track=None)` (`garage61/sync.py`). Optional body `{car?, track?}` scopes it. The endpoint constructs `Garage61Client()` (`garage61/client.py`, which reads `GARAGE61_TOKEN` from the environment and raises if unset) — it **never** reads a token from the request. Returns the `list[CohortSync]` summaries verbatim (laps seen / imported / skipped per cohort). No aggregation or recomputation in the endpoint.
  2. `POST /api/cohorts/{slug}/rebuild-map` resolves the slug via the existing `resolve()` and wraps `rebuild_cohort_map(db, *, driver, car, track, config)` (`pipeline.py`). Returns the result verbatim (per-corner centroid shift, window-changed, laps re-measured, laps cleared, admitted, class changes, `total_cleared`). A missing map → 404, mirroring the CLI's exit-2. It rewrites frozen geometry, so its UI control is behind an explicit, distinct confirm (decision 5), like the config apply.
  3. **CLI-effect parity (the binding decision-3 condition), tested for each:** the endpoint's DB and audit effects are byte-identical to the CLI equivalent (`driverdna sync` / `driverdna rebuild-map`) on an equivalent DB — the same test shape `tests/test_upload_api.py` uses for `/api/laps/upload`. The sync parity test drives a **mocked** `Garage61Client` (canned lap listing + CSV bytes) on both sides — never a live API and never a real token (testing rule); the rebuild parity test runs endpoint vs CLI on two copies of one real fixture cohort and asserts identical `corner_maps` / phase-time rows.
  4. **Token is env-only, proven:** a test asserts that with `GARAGE61_TOKEN` unset, `POST /api/sync` returns a directive error (4xx with an actionable detail) and writes nothing; the token is never accepted from, or echoed to, the request. The UI renders that state as guidance ("Set GARAGE61_TOKEN to sync"), **never an input field** — secrets never transit the browser.
  5. **UI, in the v2 button system:** a **Sync** button (driver-wide — driver home and/or Garage) renders the sync counts verbatim; a **Rebuild map** button (cohort context strip) sits behind its own confirm and renders the rebuild report verbatim, including the cleared-stale-phase notice. Every figure shown traces to the endpoint response (render parity) — the SPA never recomputes a count or a shift.
  6. **Trust gates stay green.** Sync/rebuild are actions on existing views, so no new hash route is required; if a dedicated results route is added, it joins the offline route list (and the parity list only if it renders a measurement, per the U5 finding). No new external network path except the sync endpoint's server-side Garage61 call through the existing client; the SPA still makes only same-origin `/api` calls (offline gate).
  7. Records: a dated PROJECT-BRIEF.md decision-log entry and a STATUS.md line on completion; this milestone's own text updated to "built" with any implementation-time deviations flagged, exactly as U5 did.

Strict order; a milestone begins only when the prior one's gates pass.

## Trust gates

1. Render parity: no number on screen absent from the payload or a read endpoint (U1 crawler test, kept green forever).
2. Gate visibility: on a fixture DB with known suppressions, every suppressed finding appears with its reason; the count of gate-suppressed items is always on screen where findings show.
3. Confirm discipline: an unconfirmed proposal changes nothing (e2e); a confirmed one writes through `ConfigStore` with a history entry and is revertible from the UI.
4. Validation before display: a mocked provider response citing an unknown evidence ID never renders; the UI shows the surfaced error instead.
5. Offline: the app fully loads and operates with all non-localhost network blocked.

## Out of scope

Split per A17 (2026-07-20, SPEC.md amendment log; full record in
PROJECT-BRIEF.md's decision log): philosophy #8 is refined to "personal
instrument first" — product potential is acknowledged and deferred, so the
exclusions below are no longer one undifferentiated list.

**Permanent — trust properties, not v1 conveniences.** These hold in any
future form of DriverDNA, productized or not: editing measurements,
client-side computation of any figure, blended scores in any form, setup
advice surfaces (no setup data exists to ground them).

**v1-only — deferred, revisitable after the instrument is proven on its
owner (post-M6, post-blind-test).** Authentication and multi-user, hosted
deployment, mobile app, Tauri/Electron packaging (deferred, not designed
against). Any revisit keeps the permanent list above intact.

## Setup notes

Lives at `docs/UI-SPEC.md`; add the amendment reference in `docs/SPEC.md` and a UI section to `CLAUDE.md` build rules (node at build time only; `npm run build` emits into the package static dir; API tests never require node). Build order U0 → U4 after the engine's blind acceptance test has been run — rendering an unvalidated instrument beautifully is polish in the wrong place.

**Owner amendment (2026-07-19):** U0 and U1 proceed ahead of the blind
acceptance test, accepting the risk stated above (owner's explicit call, for
momentum). U2–U4 keep the original gate: revisit when reached — either the
blind test has run by then, or the owner decides again, recorded here.

**Owner amendments, continued (2026-07-19/20):** the gate was revisited as
required, each time by explicit owner call recorded in PROJECT-BRIEF.md's
decision log: U2 built ahead of the blind test (2026-07-19, same momentum
rationale), then U3 (2026-07-20 — UI plumbing over the already-mock-tested
`ChatSession` and the render-parity crawler's grounding guarantee, not a new
measurement claim; the same reasoning covers U4, which is packaging). The
blind acceptance test remains the trust gate for the *engine's findings*,
still pending the owner's independent multi-session Spa data.

**Owner amendment (2026-07-22):** design language v2 ("pit wall") adopted at
spec stage — owner directive: keep the palette; add simplicity, more
buttons, and a small tinge of personality, with iRacing's UI/promotional
language as the register reference. Adds view 8 (Garage), milestones U5–U6,
and amends the base typography clause (one functional condensed display
face for structure labels). Colors, color grammar, trust gates, and the
philosophy are untouched. Mockup: `docs/ui-redesign-mockup.html`
(placeholder numbers, labeled as such). Build follows the standing
discipline: U5 begins on the owner's go, U6 only after U5's gates pass.
Full record: PROJECT-BRIEF.md decision log, 2026-07-22.
