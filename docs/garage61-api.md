# Garage61 API report (M0b)

Probed 2026-07-20 against the live API with a real `GARAGE61_TOKEN`
(scopes granted: `profile`, `openid`, `driving_data`; free subscription
plan). Cross-referenced 2026-07-21 against Garage61's own developer-portal
pages (Getting started, Authentication, Permissions, Endpoints, Webhooks —
owner-supplied, since the live site is a JS-rendered SPA this session's
tooling can't fetch). Facts below are tagged by source: **observed** (an
actual HTTP response from this account/token), **per official docs**
(stated in Garage61's own developer documentation, not independently
re-verified against this token), or **unconfirmed** (neither — do not
build on it without checking first). The token was passed only as an
environment variable to throwaway probe scripts for this session; it was
never written to disk, logged, or committed, and no request/response
evidence containing it was saved. Third-party drivers' names encountered
while probing shared/team endpoints are redacted below (`Driver B`,
`Driver C`, ...); only the probing account's own data and structural
facts are reported.

**Per official docs, standing caveat:** "there is no API stability yet" —
Garage61 states the API may change at any point, with best-effort (not
guaranteed) advance notice of breaking changes. `sync` should be treated
as built against a moving target, not a frozen contract.

## Base URL, versioning, auth

- Base URL: `https://garage61.net/api/v1`
- Auth: `Authorization: Bearer <GARAGE61_TOKEN>` on every request.
- Missing header → `401 {"message": "Missing authorization: supply a
  Bearer token in the Authorization header."}`
- Invalid/garbage token → `401 {"message": "Bad authentication: operation
  Me: security \"OAuth2\": invalid access token."}`
- Every response carries `X-G61-Trace` (a per-request trace id) — worth
  logging on error for support purposes, never as a secret.

## Permissions (per official docs) — this explains the 403 finding below

Every token carries a set of granted permissions (observed on this token,
via `/me.apiPermissions`: `profile`, `openid`, `driving_data`). Per
official docs, the permission relevant to `sync` is:

- **`driving_data`** — "Allows access to the driving data (activity,
  telemetry and setups) that is **visible to the authenticated user** in
  the application. This is still subject to the privacy settings in the
  application: the API application will have the exact same view on data
  as the user. If a team mate does not share setups, you won't find them
  in the API either. **By default, applications can only query the
  authenticated user and their teammates.** Some applications may
  additionally be approved to search all driving data that is visible to
  the authenticated user." Requires app-level approval + the user opting
  in (both already true for this token, since `driving_data` shows up on
  `/me`).

**This explains, not just describes, the 403 `forbidden_lap` finding
below**: this token's default `driving_data` scope is self + teammates
only. The driver whose lap 403'd (surfaced through an unscoped `/laps`
listing) was not a teammate of the probing account — consistent with the
documented default. `/laps` *listing* itself showing ~30–66 non-teammate
drivers per query is not contradictory: per official docs, some
applications get **search** approved beyond the default scope even where
per-lap **access** (detail/CSV) stays gated to self+teammates+sharing —
metadata visibility and content access are different gates. This is the
most coherent reading of the observed 403-on-non-teammate + broad-listing
combination, not an independently re-verified mechanism.

Permissions this token does **not** have, each requiring separate app
approval and (for most) the driver's own opt-in — listed because two are
directly relevant to `sync`'s reference-lap question (see the data-packs
note further down):

- **`analyses`** — access to the authenticated user's own analyses
  (telemetry analysis / laps, and training-plan results). A different
  permission from `driving_data`; untested here (not granted).
- **`team_datapacks_read`** (+ `_archived_read`, `_subscribers_read`,
  `team_datapacks_write`) — read/write access to a team's **data packs**:
  team-curated shared content (see "Team data packs" below).
- **`datapacks_subscriptions`**, **`team_trainingplans_read`**,
  **`team_members`** — not relevant to DriverDNA's scope.

## List/lookup endpoints (all `GET`, all return `{"items": [...], "total": N}`)

`/me`, `/me/accounts`, `/me/statistics`, `/teams`, `/teams/{team_id}`,
`/teams/{team_id}/statistics`, `/cars`, `/tracks`, `/platforms`,
`/car-groups` — all returned `200` with no required parameters.
`/me/statistics` returns per-day driving-activity rows (`day`, `car`,
`track`, `sessionType`, `events`, `timeOnTrack`, `lapsDriven`,
`cleanLapsDriven`) — a practical way for `sync` to discover which
(car, track) cohorts the account has driven, without an unscoped lap
listing call (see below, `/laps` has none).

`/cars` and `/tracks` return small integer IDs (`car.id`, `track.id`),
not the iRacing `platform_id` strings — these integer IDs are what
`/laps`'s `cars`/`tracks` filters expect.

## Lap listing — `/laps`

- **`tracks` is a required query parameter.** Omitting it →
  `400 {"error_message": "operation FindLaps: decode params: query:
  \"tracks\": query parameter \"tracks\" not set"}`. `sync` cannot do one
  unscoped "everything since last sync" call; it must drive listing from
  known (car, track) cohorts, e.g. discovered via `/me/statistics`.
- `tracks` and (optionally) `cars` accept a single integer id or a
  comma-separated list (`tracks=69,498` observably widened the result
  `total` from 66 to 88). A non-integer value for `cars` is rejected:
  `400 {"error_message": "operation FindLaps: decode params: query:
  \"cars\": strconv.ParseInt: parsing \"not-a-real-id\": invalid syntax"}`.
- **Pagination:** `limit` and `offset`. `offset`-paged pages returned
  disjoint id sets (verified: page1 ∩ page2 = ∅) and every response
  carries `total`. `limit=5000`, `limit=0`, and `limit=-1` all silently
  fell back to returning the full set (66 of 66) rather than erroring —
  consistent with a default/max around 1000 (matches third-party client
  docs) but **the exact upper bound is unconfirmed**; no query in this
  probe had more than 88 total matches, so a true >1000-result page was
  never exercised.
- **Filters attempted that did not observably work:** `start`/`end`
  (date range), `teams`, `accounts` — sending these did not change
  `total` or the returned items versus omitting them, same as a
  deliberately misspelled parameter name (`thisparamdoesnotexist`) tried
  as a control, which also had zero effect. This API silently ignores
  unrecognized query names rather than rejecting them (contrast with
  `cars`, a recognized name, which does reject bad values). **The correct
  parameter names for date-range and team/account-scoped filtering are
  unconfirmed** — the official endpoint reference
  (`https://garage61.net/developer/endpoints`) is a JS-rendered SPA not
  reachable by this session's fetch tooling, so it could not be consulted
  in this pass. Do not build `sync` filtering on `start`/`end`/`teams`/
  `accounts` without re-verifying param names first.
- **`/laps` is not scoped to "my own laps" by default.** A plain
  `tracks=69` query returned laps from ~30 distinct drivers (own account
  included), not just the token's account. Reliable self-scoping observed
  to work: filter client-side on the embedded `driver.id` field of each
  returned lap (`driver.id == /me`'s `id`) — every list item carries a
  full `driver` object (`id`, `slug`, `firstName`, `lastName`), so this
  needs no extra request.
- **`/laps` returns at most one lap per driver per (car, track) — a
  leaderboard/PB endpoint, not a full session log, confirmed universal
  across drivers, not an account-specific cap.** Census 2026-07-20: the
  probed account's own retrievable laps totalled **26 — exactly one per
  (car, track) cohort** (max in any single cohort: 1), against **979 laps
  driven** per `/me/statistics` (up to 163 in one cohort) — so `/laps`
  clearly isn't a full log. Initially hypothesized as a free-plan cap
  (`subscriptionPlan: "free"` on `/me`) specific to this account — **ruled
  out** by a follow-up check: in a shared cohort with 30 distinct drivers
  (Okayama/Mazda MX-5) and again with 66 distinct drivers (Okayama, all
  cars), **every single driver had exactly 1 lap, no exceptions**
  (`Counter({1: 30})` and `Counter({1: 66})` — zero drivers with >1). One
  row per driver per cohort is `/laps`'s behavior for everyone, not a
  plan-gated limit on this account. Per official docs, the endpoint's own
  description is "**Find laps and lap records**" — wording that supports
  (without fully proving) the lap-record/personal-best-per-driver-per-combo
  reading over a raw per-driver log; the exact rule (best time vs most
  recent vs something else) remains unconfirmed. **Consequence:** `sync` already
  pulls everything `/laps` returns; this is the endpoint's shape, not an
  under-pull, and not something a different plan or more API calls can
  pull around. M6's per-cohort trend (avoiding the cross-cohort
  bucket-composition confound) needs many laps *per cohort*, which this
  endpoint cannot supply for any account — it would need a dated
  manual-import path for locally-exported CSVs instead.

## Single-lap detail and CSV — `/laps/{lap_id}`, `/laps/{lap_id}/csv`

- Own-account lap: both endpoints → `200`. `/laps/{id}/csv` for a real
  lap (own account, Mazda MX-5 @ a track this account raced) returned a
  1,079,965-byte CSV, 6,926 data rows (115.43 s at 60 Hz, plausible for
  the car/track). **Header, column order, and units exactly match the
  manual-download source contract already locked by M0a**:
  - Header string identical, same order: `Speed,LapDistPct,Lat,Lon,
    Brake,Throttle,RPM,SteeringWheelAngle,Gear,Clutch,ABSActive,
    DRSActive,LatAccel,LongAccel,VertAccel,Yaw,YawRate,PositionType`
  - `Speed` in m/s (observed max 49.3 m/s ≈ 177.6 km/h, plausible)
  - `ABSActive`/`DRSActive` string `"true"`/`"false"`
  - `Clutch` pinned at `1` throughout (matches the known fixture fact)
  - `LapDistPct` runs 0→1 across the lap (single-lap contract holds)
  - `SteeringWheelAngle` in the same radian range as the fixtures
- A lap owned by a different driver (surfaced through the unscoped
  `/laps` listing above): both `/laps/{id}` and `/laps/{id}/csv` →
  `403 {"message": "No permission to view this lap.", "code":
  "forbidden_lap"}`. This is a distinct error shape from a nonexistent
  lap id (`404 {"message": "Lap not found"}`), and distinct from an
  auth failure (`401`) — the API can tell "exists, not yours" from
  "doesn't exist," it just returns 404 either way for an id that's
  neither. (A synthetic 26-char id and every real fixture LAPID both
  produced `404`, not `403` — see Parity check below for why.)
  - Both teams the probing account belongs to were checked
    (`/teams/{id}`, `/teams/{id}/statistics`) — neither surfaced a lap
    from a *fellow team member* to test against, so **whether team
    membership/consent unlocks detail+CSV access (vs. a hard per-plan
    restriction) is unconfirmed** — this probe only demonstrates the
    "unrelated driver" case.

## The reference-lap question — resolved for `/laps`; a second, unexplored path exists

Decision-of-record #2 and the M0b spec both name this the "one genuine
unknown": can this token fetch laps shared by other drivers? **Via
`/laps`, observed answer: no.** Other drivers' laps are visible in `/laps`
list results (track/car scoped, not owner-scoped) but their detail and CSV
endpoints return `403 forbidden_lap`. Own-account laps work fully. Per
official docs (Permissions, above), this is consistent with `driving_data`
defaulting to self + teammates: the 403'd driver in this probe wasn't a
teammate. Per SPEC.md's already-written contingency ("If other-driver
fetch is unavailable, reference laps degrade to manual-download import
tagged `reference`"), **the reference-lap feature uses the manual `import`
path for laps reached via `/laps`**, until/unless a teammate relationship
is confirmed to change the 403 outcome (still untested — no teammate lap
was available to probe against).

**A structurally different path exists and is unexplored: team data
packs.** Per official docs (Endpoints, Permissions), a team can curate and
publish shared content via a whole separate subsystem —
`GET/POST/DELETE /api/v1/teams/{team}/datapacks*` — including
`GET .../content/{item}/lap.csv` (telemetry export for a data-pack lap),
plus ghost-lap and iRacing-setup downloads. This is gated by its own
permissions (`team_datapacks_read`, `_write`, `_subscribers_read`,
`_archived_read` — all "requires approval" + "requires user acceptance"),
**none of which this token has**, so it is completely untested here — not
ruled out, just not reached. Unlike `/laps` (an ad-hoc, per-lap
"is this driver visible to me" check that legitimately 403s on strangers),
data packs are Garage61's own explicit content-*sharing* mechanism — a
coach or team publishing reference material for members to pull. If
DriverDNA's reference-lap feature is ever revisited, this is the
mechanism to probe next, not another attempt at `/laps` with a different
plan tier. Requires: the app registered for `team_datapacks_read`
(approval), the driver opting in, and — since data packs are
team-scoped — an actual team whose owner has published lap content to
subscribe to. Recorded here so a future session starts from this position
instead of re-deriving it (SPEC.md decision-of-record #2 is not reopened
by this note — manual `import` remains correct for v1 until data packs
are actually probed and shown to work).

## Parity check

Every lap id in `tests/fixtures/manifest.toml`
(`RH11X7`, `HKWPXX`, `W5JRZB`, `K56YRV`, `VHC6M4`, `WC6PRT`, `WN30FK`,
`5HAH7B`, `ZE3WQQ`, `B3M5ZW`, `59384F`, `5ZBWTZ`) was tried against
`/laps/{lap_id}` and every one returned `404 Lap not found`.

**Finding:** the short code Garage61 embeds in a manually-downloaded
filename (`Garage_61_<LAPID>.csv`) is **not** the API's lap identifier.
The API's `id` field is a 26-character ULID (e.g.
`01KVNRRWZVY7QY49HK6MWMESDV`); the filename code is a different, shorter
scheme. This means a byte-for-byte parity diff against the exact fixture
files was not possible in this probe — there is no way to resolve a
filename-derived `LAPID` to an API lap id (and thus no way to `/laps/{id}
/csv` a specific already-downloaded file) without also having captured
the API `id` at download time, which the fixtures predate. **Consequence
for `sync`:** never attempt to look up a lap by the filename-embedded
code; the two ID spaces are unrelated. Structural parity (header, column
order, units, dirty-data character) was instead confirmed against a
freshly API-fetched own-account lap, as detailed above, and matches the
locked M0a contract exactly.

## Rate limits

No `X-RateLimit-*` or `Retry-After` response headers were observed on any
call, and a burst of 8 back-to-back `GET /me` calls (~0.7–1.0 s each,
~7 s total) all returned `200` with no slowdown or `429`. This is a
narrow, light-load probe — it shows no limit was hit under this load, not
that no limit exists. `sync` should still apply conservative pacing
between requests and handle `429`/`Retry-After` defensively even though
neither was observed here.

## Error shape summary

| Status | Body shape | Observed cause |
|---|---|---|
| 400 | `{"error_message": "..."}` | missing required query param (`tracks`); wrong-typed value (`cars` not an int) |
| 401 | `{"message": "...", "trace": "..."}` | missing or invalid bearer token |
| 403 | `{"message": "...", "code": "forbidden_lap", "trace": "..."}` | lap detail/CSV for a lap the token doesn't own |
| 404 | `{"message": "Lap not found", "trace": "..."}` | lap id doesn't exist *or* isn't visible to this token (indistinguishable) |

## Other documented endpoints/subsystems, not probed (per official docs)

Recorded so a future session knows these exist without re-discovering them
from scratch; none of this is used by `sync` today.

- **`GET /analyses`, `GET /analyses/{id}`** — "Analyses for current user,"
  including "telemetry analysis (laps), but also training plan results."
  Gated by the `analyses` permission (not granted to this token) — a
  *different* permission from `driving_data`, so untested whether this
  route's data shape or lap coverage differs from `/laps`. Worth probing
  before assuming `/laps`'s one-per-driver-per-cohort shape also applies
  here.
- **`GET /teams/{team}/statistics`** — a team-scoped variant of
  `/me/statistics`, which was probed and is what `sync`'s cohort discovery
  actually uses (the personal one, not this). The team variant exists but
  isn't used by anything here.
- **Training plans** (`GET /teams/{team}/trainingplans[/{id}]`) — out of
  scope for DriverDNA (no coaching-plan-authoring feature exists here).
- **Team membership writes** (`POST .../invites`, `DELETE .../members/{id}`)
  — administrative, out of scope; DriverDNA is read-mostly except the
  audited `sync`/`import` paths.
- **OAuth2** (Authorization URL `https://garage61.net/app/account/oauth`,
  Token URL `https://garage61.net/api/oauth/token`, User Info URL
  `https://garage61.net/api/oauth/userinfo`, Authorization Code Grant +
  PKCE) — the alternative to a personal access token, for an app used by
  *many* users each authorizing their own access. `sync` uses a personal
  access token (decision-of-record #1's ingestion design assumes one
  driver, one token) and has no reason to need OAuth2 unless DriverDNA
  is ever productized for multiple users (A17 — deferred, not v1).
- **Webhooks** (live timing) — a push-based event stream, HMAC-SHA256
  signed (`X-Garage61-Timestamp` + `X-Garage61-Signature: v1=<hex>`,
  `message = "<timestamp>.<raw body>"`), delivering session/lap/pit
  events in real time: `START_SESSION`, `SESSION_PARTICIPANT_UPDATE`,
  `INITIAL_STINT_STARTED`, `STINT_COMPLETED`, `PIT_IN`, `PIT_OUT`,
  `DRIVER_CHANGE`, `LAP_COMPLETED`, `LAP_TIME_UPDATED`, `RUNNER_RESUMED`,
  `RUNNER_SHUTDOWN`. This is a fundamentally different ingestion model
  from `sync`'s pull-based polling — live, not historical — and would
  need a webhook receiver (a public endpoint, out of keeping with
  philosophy #8's "local, no server" v1 design) to use. Recorded for
  completeness; not a fit for `sync` as designed, and not proposed here.

## Capabilities summary → implications for building `sync`

- ✅ Auth, own-lap listing (track/car-scoped + client-side self-filter on
  `driver.id`), single-lap CSV fetch, pagination (`limit`/`offset` +
  `total`) all work and are ready to build on.
- ✅ CSV format from the API matches the manual-download contract
  exactly — the existing `Garage61Parser` needs no format changes to
  accept API-sourced CSVs.
- ❌ Other-driver ("reference") lap fetch via `/laps` is **not available**
  with this token (`driving_data`'s default scope is self+teammates, per
  official docs) — reference laps stay on the manual `import` path,
  `role=reference`, as already specified. **Team data packs are a
  separate, unexplored mechanism** that might legitimately serve
  reference laps without hitting this wall — untested, requires
  `team_datapacks_read` app approval this token doesn't have (see "Other
  documented endpoints" above).
- ⚠️ `sync` must discover cohorts via `/me/statistics` (or a
  driver-supplied car/track list) and loop `/laps?tracks=...&cars=...`
  per cohort — there is no unscoped "give me everything" call.
- ⚠️ `/laps` returns **at most one lap per driver per cohort, confirmed
  universal** (every driver in two independently-checked shared cohorts —
  30 and 66 drivers — had exactly 1, no exceptions) — not a plan-specific
  cap on this account. vs 979 laps driven per `/me/statistics`. `sync`
  pulls all of them, so it's the endpoint's shape, not an under-pull: M6's
  per-cohort trend needs a dated manual-import path for locally-exported
  CSVs instead — no account or API call sequence can pull more per cohort
  from `/laps`.
- ⚠️ Unconfirmed, do not assume before re-checking: the real query-param
  names for date-range and team/account-scoped filtering; the exact
  `limit` ceiling; whether team-shared consent changes the 403 outcome;
  exact rate-limit thresholds.

Done per M0b's criteria: this document exists and API capabilities are
enumerated from observed behavior, including the one genuine unknown the
milestone existed to resolve (other-driver lap fetchability).
