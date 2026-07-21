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
`POST /api/findings/{id}/annotate` · `POST /api/config/propose` · `POST /api/config/apply` · `POST /api/chat/sessions` · `POST /api/chat/sessions/{id}/messages` (response via SSE per decision 4) · `POST /api/chat/sessions/{id}/confirm/{n}`.

## Views

1. **Driver home.** Cumulative seconds lost by technique (the product's headline claim), per-class breakdown, session trend, and the gates panel: every suppressed rollup with reason and progress. If nothing clears the gates yet, this page *is* the gates panel plus what to do next.
2. **Cohort (car + track).** The signature element: a track outline drawn from a representative retained lap's `Lat`/`Lon` trace, with corner markers at the frozen apex-cluster positions, colored by attributed cumulative loss and badged by class — the instrument rendering the driver's actual data, not a stock map. This is the one bold element in the product; everything around it stays quiet. Beside it, findings in three source sections, and the corner list.
3. **Corner drill.** Phase deltas vs the labeled baselines (median-of-top-3 primary, single-best labeled, reference gap when present), metric distributions, lap-over-lap trend, landmarks over the canonical window. All series straight from payload or the distribution endpoint.
4. **Finding detail.** The evidence view: N, spread, source tag, confidence context, evidence IDs resolving to real laps and corners (deep-linked), plain-language principle rationale where applicable, and the annotate actions (acknowledged / intentional) with their effect stated before use.
5. **Chat.** Grounded session per decision 4/5. Evidence IDs in responses are links into views 3–4. Staged proposals render as a distinct card; `Confirm change` is its own labeled action.
6. **Config.** Snapshot with per-key documentation, edits flowing through propose/apply, and `config_history` as the audit view with revert.
7. **Laps.** Import/session listing with quality flags surfaced (clipped pedals, GPS-degraded, outlier screens) — the data-quality conscience of the instrument.

## Design language and tokens

This section is the visual source of truth for both surfaces: the SPA and the static HTML report templates, which are brought onto the same tokens during U4 so the product has one appearance. Tokens live in a single file (`ui/tokens.json`) consumed by both.

Ground it in the subject: this is a measurement instrument for motorsport, and the sport already has a visual language — timing screens and telemetry software. The palette adopts that vernacular rather than inventing one, so it reads instantly to a racer.

**Color grammar — three rules governing every screen:**

1. Color encodes measurement semantics only, per international timing convention: purple = best (fastest execution, session best); green = at or under baseline; amber = off pace / attention; red = data-quality problems and errors **only, never driver pace** — the instrument does not editorialize about driving with alarm color.
2. The three source tags are differentiated structurally — labeled eyebrows, distinct left-rule styles, tag chips — never by the semantic colors above, so a section's identity can never be mistaken for a verdict.
3. Interaction (links, focus, selection) uses one quiet accent distinct from every semantic color, so nothing interactive masquerades as data.

**Tokens (defaults; tunable in one place):** ground in layered dark neutrals — base `#101318`, panel `#171B22`, raised `#1F242D`, line `#2A303A`; text `#E8EAED` primary / `#8C93A0` dim. Semantic: purple `#B48CFF`, green `#3ECF8E`, amber `#E8A13C`, red `#E5484D`. Interactive accent: muted steel `#6EA8D8`, used sparingly. Dark-only in v1; the token layer keeps a light theme possible, not promised.

**Typography:** every figure set in a monospaced face with tabular numerals (IBM Plex Mono, bundled) — a number is never proportional; UI text in a neutral grotesk (IBM Plex Sans, bundled); no decorative display face. Data tables run timing-screen dense; interactive controls keep full hit areas.

**Motion:** functional only — state transitions ≤ 150 ms, no chart entrance animation, `prefers-reduced-motion` honored.

**States:** gated/suppressed items keep full structure at reduced emphasis with their reason line — legible, never faded to invisibility. Annotated findings sit in their own labeled group, measurement visible. A staged config proposal renders as an amber-ruled card (attention semantics) until confirmed or discarded.

**Copy:** the product's fixed vocabulary — findings, gates, evidence, sources, staged, confirmed — one name per concept everywhere. Errors and empty states give direction, not mood. Quality floor without announcement: visible keyboard focus, readable at laptop and phone widths.

## Milestones

- **U0 — API layer.** All endpoints above; contract tests: payload endpoints byte-identical to `driverdna report` JSON on a fixture DB; each write endpoint's effects identical to the CLI equivalent; nothing importable from the SPA to compute.
- **U1 — Read-only views.** Driver home, cohort (with track rendering), corner drill, finding detail, laps. Render-parity test: crawl every number in rendered output on the fixture DB and assert each exists in the payload/read endpoints.
- **U2 — Writes.** Annotations and config panel through the gated paths; audit visible in-UI.
- **U3 — Chat.** SSE progress, validated-only rendering, tool-call audit, staged/confirm flow end to end.
- **U4 — Packaging & polish. Done (2026-07-21).** `driverdna ui` command, built assets shipped in-package — already true since U0. This pass closed the remaining gaps: the static HTML report templates migrated onto `ui/tokens.json` (`report/builder.py`'s `_TOKENS`, kept in sync by a test that reads the real JSON file; chart colors mirror the SPA's own `app.css` convention exactly — neutral fill, single max value in `--warn`); fonts self-hosted in the SPA (`@fontsource`, latin subset, the weights actually used); and offline verification became a real dynamic test (trust gate 5) — Playwright actively blocking every non-localhost request across every route, not a static grep. Report HTML determinism (byte-identical across independent renders) is now its own test, closing a gap this milestone's own text named. A broader visual "design pass" beyond color/type/offline was not separately re-audited — U1–U3 already built the SPA against this document's rules directly.

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
