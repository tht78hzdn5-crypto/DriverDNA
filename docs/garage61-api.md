# Garage61 API report (M0b)

> ## Correction, 2026-07-27 (SPEC.md A28) — read this before anything below
>
> **This document's headline finding was wrong.** It concluded that `/laps`
> "returns at most one lap per driver per (car, track) — a leaderboard/PB
> endpoint, not a full session log," and that this was "the endpoint's shape
> … not something a different plan or more API calls can pull around."
>
> It is a **query-parameter default**. `group` defaults to `driver`
> ("Personal best laps per driver"); **`group=none` returns all laps.**
>
> The census that produced the claim was sound — every driver in two shared
> cohorts (30 and 66 drivers) really did have exactly one lap. The *inference*
> was not: "universal across accounts" rules out an account-specific cause,
> but a parameter default is equally universal, and a probe that never varies
> the parameter cannot see it. The conclusion should have been "one lap per
> driver per cohort under the parameters we sent."
>
> The correction came from a Garage61 engineer (Alex) by email, and was then
> confirmed against Garage61's own OpenAPI document — which this document had
> declared unreachable. That was the second error, and the more useful one:
>
> **The developer portal is a JS SPA, but it fetches a plain JSON spec, and
> the URL is a literal string in its own bundle:**
> **`https://garage61.net/api/openapi/v1.json`** (no token required).
> When a docs site won't render, read its client before concluding the
> documentation is unavailable.
>
> Sections below are left as originally written, with inline `**Corrected
> (A28)**` notes where they are now known to be wrong. Everything sourced
> from the OpenAPI document is tagged **per spec** — that is official
> documentation, but it is *not* the same tag as **observed**: the session
> that applied this correction had no `GARAGE61_TOKEN`, so no claim here
> marked "per spec" has been re-verified against a live call. See "Spec-
> sourced lap filtering (A28)" below for the full parameter list.

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

  > **Corrected (A28).** The names were simply wrong, which is exactly what
  > "silently ignores unrecognized names" predicts. Per spec, date filtering
  > is **`after`** (RFC3339 date-time) and **`age`** (positive = days ago;
  > `-1`/`-2`/`-3`/`-4` = current season / current+previous / last 3 / last
  > 4). `teams` *is* real (by team **slug**), alongside `drivers`
  > (`me`, `following`) and `extraDrivers` (by user slug); `accounts` is
  > not a parameter. The lesson stands and generalises: against an API that
  > ignores unknown parameters, a no-op is evidence about the *name*, never
  > about the *capability*.
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

  > **Corrected (A28) — this whole bullet's conclusion is wrong.** The
  > observation (1 lap per driver per cohort, universal) was real; the
  > explanation was not. Per spec, `group` defaults to `driver` = "Personal
  > best laps per driver", and **`group=none` = "Return all laps."** The
  > "lap records" wording in the endpoint's own summary was a genuine clue
  > read as confirmation of a limit rather than as a hint to look for the
  > switch. `sync` sends `group=none` since A28.
  >
  > "Not something more API calls can pull around" was the specific
  > overreach: a universal observation constrains *what the parameters we
  > sent do*, never *what the endpoint can do*. Note also that
  > `group=driver-car` exists (PB per driver **per car**), which is why the
  > count tracked cohorts so exactly.
  >
  > M6's per-cohort trend is therefore reachable from the API after all.
  > Dated manual import (2026-07-21) is still the only path for pre-API
  > history and laps Garage61 never held, so it is not retired.

## Spec-sourced lap filtering (A28, 2026-07-27) — `/laps` parameters

**Source: `https://garage61.net/api/openapi/v1.json`** (operation
`findLaps`), the JSON the developer portal's own SPA renders. Fetched
without a token 2026-07-27. Everything in this section is **per spec** and
**not live-verified** — the session that wrote it had no `GARAGE61_TOKEN`.
Given that this API silently ignores query names it does not recognise, an
unverified parameter fails *silently and permissively* (returning more than
intended), which is why `sync` keeps its client-side self-filter regardless.

The parameters DriverDNA uses or could use:

| Parameter | Type | Meaning (spec wording, condensed) |
|---|---|---|
| `tracks` | int list | **Required.** Track IDs. |
| `cars` | int list | Car IDs. **Negative = car *category* ID** (`cars=3,-4` = car 3 or category 4). |
| `group` | string | Result grouping, **default `driver`**: `driver` = PB per driver; `driver-car` = PB per driver/car; **`none` = return all laps**. |
| `drivers` | string list | `me` (own laps), `following`. Combined with `teams`/`extraDrivers`. If none given, defaults to all data visible to the token. |
| `teams` | string list | Teammates from the given teams, by team **slug**. |
| `extraDrivers` | string list | Extra drivers by user **slug**. |
| `after` | RFC3339 date-time | Laps driven after this instant. |
| `age` | int | Positive = max days ago. Negative: `-1` current season, `-2` current+previous, `-3` last 3, `-4` last 4. |
| `lapTypes` | int list | **Default: normal laps only.** `1` normal (full), `2` joker, `3` out lap, `4` in lap. |
| `unclean` | bool | Allow returning unclean (and potentially incomplete) laps. |
| `sessionTypes` | int list | `1` practice, `2` qualifying, `3` race. |
| `event` | string | Laps for one event ID (pairs with each lap's own `event` field). |
| `seeTelemetry` | bool | Require telemetry to be visible. **"Requires the calling user to have a Pro plan."** |
| `minLapTime` / `maxLapTime` | number | Lap-time bounds, seconds. |
| `limit` | int | **Maximum and default are both 1000.** |
| `offset` | int | Result offset. |

Also available and unused here: `seasons`, `sessionSetupTypes`, `seeGhostLap`,
`seeSetup`, `minRating`/`maxRating`, fuel bounds, weight-penalty and
power-adjust bounds, a full set of track/weather-condition bounds
(`minConditionsTrackTemp`, `maxConditionsTrackWetness`, …), and `round`
(display-rounding correction, `metric` / `englishStandard`).

**What `sync` sends** (`garage61/client.py`): `tracks`, `cars`, `limit`,
`offset`, `group=none`, `drivers=me`, `unclean=true`, and `after`/`age` when
the driver supplies them. `lapTypes` is deliberately **not** sent — its
default is normal full laps, which is exactly M0a's single-lap contract; in
and out laps would violate the `LapDistPct` 0→1 invariant.

### Lap fields relevant to ingest (per spec)

The `Lap` schema marks these **required**, so they should always be present.
Two matter for A28 specifically:

- **`canViewTelemetry`** (bool) — "Can you view the telemetry data?" This is
  how `sync` decides whether a CSV fetch is worth attempting, rather than
  discovering it as a 403. Given `seeTelemetry`'s documented Pro-plan
  requirement and the owner's free plan, this is the field that determines
  whether A28's unlock is real for this account. **Unverified against a live
  call** — if a free plan reports `false` for non-PB laps, `sync` will report
  "listed but telemetry not viewable" per cohort and import nothing for them,
  which is the honest outcome rather than a failure.
- **`clean`** (bool) — "Is this a clean, complete lap?" Recorded in the
  existing `api_lap_metadata` quality flag. With `unclean=true`, laps where
  this is `false` now reach the pipeline by design (A19).

Others already used or worth knowing: `id`, `driver`, `event`, `session`,
`run`, `startTime`, `lapNumber`, `lapTime` (seconds), `sectors`,
`sessionType`, `eventType`, `missing`, `incomplete`, `offtrack`,
`discontinuity`, `pitlane`/`pitIn`/`pitOut`, `trackTemp`, `trackUsage`,
`trackWetness`, plus fuel, tyre-compound and weather fields.

### `PositionType` (per spec, matches the M0a contract)

The CSV export's `PositionType` column is documented as: `0` unknown,
`1` in the pit lane, `2` making a pit stop, `3` on track, **`4` off track**.
This independently corroborates `config.incidents.offtrack_position_value`,
which the incident subsystem (A19) uses for off-track detection.

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
**none of which this token has.** Unlike `/laps` (an ad-hoc, per-lap
"is this driver visible to me" check that legitimately 403s on strangers),
data packs are Garage61's own explicit content-*sharing* mechanism — a
coach or team publishing reference material for members to pull. If
DriverDNA's reference-lap feature is ever revisited, this is the
mechanism to probe next, not another attempt at `/laps` with a different
plan tier.

**Observed 2026-07-21:** `GET /teams/{id}/datapacks` and
`GET /teams/{id}/datapackgroups`, tried against both of the probing
account's teams, both return **`401`** (not `403`) with the identical body
`{"message": "Bad authentication: operation GetTeamDataPacks: security
\"OAuth2\": Missing app scope (not approved): team_datapacks_read.",
...}` (and `GetTeamDataPackGroups` for the groups call). This is a
**hard, application-level gate** — checked before any team- or
user-specific authorization, since the error is identical regardless of
which team is queried, or whether that team has other members. It is
*not* something the driver can grant from their own account; the
`team_datapacks_read` scope must be approved for the DriverDNA
application itself first (via the developer portal's "My applications" —
self-service toggle vs a Garage61-side approval request is itself
unconfirmed from the docs' wording). Until that scope is approved,
**whether either team actually has a published data pack is unknown and
unknowable via this API** — the 401 fires before that question is ever
reached.

**Owner's domain read (2026-07-21, not API-verified — labeled as such):**
the schema supports a `lap.csv` content item alongside `ghost.bin`/
`replay.bin`/`setup.sto`, but the owner's real-world expectation, from
using Garage61 day to day, is that data packs in practice are used for
sharing car **setups**, not lap telemetry — so even with the scope
approved, the realistic payoff for reference laps specifically is low.
On that basis, this avenue is **deprioritized, not closed**: the
approval-friction (self-service vs a Garage61-side request, still
unconfirmed) isn't worth spending against an expected-empty result.
Recorded here — including the schema fact and the owner's caveat kept
separate — so a future session starts from this position instead of
re-deriving it (SPEC.md decision-of-record #2 is not reopened by this
note — manual `import` remains correct for v1 until data packs are
actually probed and shown to work).

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

## A second, newer manual-download filename shape (observed 2026-07-21)

Laps supplied by the owner from a Ford Mustang GT4 / Summit Point Raceway
session used a different filename shape than every fixture seen before:
`Garage_61__<driver name>__<car>__<track>__<M.SS.mmm laptime>__<id>.csv`
(double-underscore delimited), versus the short `Garage_61_<LAPID>.csv`
form the M0a fixtures and the parity check above are built on. Both forms
were seen from the same Garage61 account across different sessions/exports,
so this looks like a tool version difference, not a fixed contract — CSV
column content was unaffected (`ingest/parser.py`'s parsing/dirty-data
handling never touches the filename beyond the ID it may or may not carry).

**Observed, not verified**: the new form's trailing ID is 26 characters
starting `01K...` — same length and leading-character pattern as the API's
own ULID `id` field documented above (`01KVNRRWZVY7QY49HK6MWMESDV`), unlike
the old short LAPID code this doc already found to be "a different, shorter
scheme." This suggests the newer export may embed the real API lap ID
directly, which — if true — would reopen the `/laps/{id}/csv` parity check
above for laps in this format. **Not confirmed against a live call**; flagged
for whoever next has a live `GARAGE61_TOKEN` and a lap in this filename
shape, not assumed.

**Built on this (2026-07-21)**: `ingest/parser.py`'s `parse_garage61_filename`
auto-detects car/track (and the trailing ID, used as `lap_id`) from either
newer shape — `driverdna import` (no `--car`/`--track`) and the UI's
`#/upload` (blank car/track fields) both use it, per-file, falling back
loudly (never silently) to requiring explicit car/track for files that don't
match either filename shape.

## A third manual-download filename shape (observed 2026-07-26)

A Ford Mustang GT4 / Summit Point Raceway lap downloaded by the owner from
the browser arrived as:

```
Garage 61 - Benjamin Richards - Ford Mustang GT4 - Summit Point Raceway - 01.27.017 - 01KY31T54KGGQ351PDAGJDTZJM.csv
```

Same five fields as the 2026-07-21 shape, but ` - ` delimited with a literal
space in `Garage 61`, and with real spaces inside each field instead of the
underscore word-separator. That is now three filename shapes from one
account, which is the evidence for treating filename-derived metadata as
observed rather than contracted (A13) — the CSV column content was again
unaffected.

Its trailing ID is again 26 characters starting `01K...`, carrying the same
**observed, not verified** ULID caveat as the section above — still not
confirmed against a live call.

**Built on this (2026-07-26, SPEC.md A24)**: both newer shapes go through one
splitter parameterized by prefix/delimiter/underscore-decoding, specifically
so they produce byte-identical car/track — those strings are cohort keys, and
two spellings of one car must not split a cohort in two. A filename carrying
the delimiter *inside* a field (a track named `Spa - Francorchamps`) is
refused rather than split on a guess, since the ambiguity would land in the
cohort key where a wrong value is invisible. A browser re-download's `(1)`
suffix is stripped before the fields are split, so it never enters `lap_id`;
the copy then lands as a content-hash duplicate at import, which is the
honest report. Safari's `-1` re-download form is deliberately **not**
handled — it was not observed here, and inventing it would be guessing past
the evidence; such a file falls into the loud, itemized error instead.

**Corrected 2026-07-26 (SPEC.md A25)**: the previous paragraph's `(1)`
handling was itself an unverified guess — no real re-download had happened
yet, and a leading space before the parenthesis was assumed by analogy, not
observed. The owner's own next re-download, on their own Windows machine,
produced `...PDABVEREMJ(1).csv` with **no space**, and the parser rejected
it. Both spellings (with and without the leading space) are now accepted;
only the no-space form is confirmed against a real file.

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
  `role=reference`, as already specified. **Team data packs are a separate
  mechanism, confirmed blocked at the application level** (`GET
  /teams/{id}/datapacks[groups]` → `401 Missing app scope (not approved):
  team_datapacks_read`, both teams, identical error) and **deprioritized**
  — the owner's real-world expectation is that data packs in practice hold
  setups, not lap telemetry, so the approval friction likely isn't worth
  it for this goal (see "team data packs" in the reference-lap section).
- ⚠️ `sync` must discover cohorts via `/me/statistics` (or a
  driver-supplied car/track list) and loop `/laps?tracks=...&cars=...`
  per cohort — there is no unscoped "give me everything" call. (Still true:
  `tracks` is required per spec.)
- ~~⚠️ `/laps` returns **at most one lap per driver per cohort**~~ —
  **withdrawn (A28)**: that was `group`'s default (`driver`), not the
  endpoint's shape. `group=none` returns all laps, and `sync` now sends it.
  The observation (every driver in two shared cohorts — 30 and 66 drivers —
  had exactly 1, vs 979 laps driven per `/me/statistics`) was accurate; the
  conclusion drawn from it was not.
- ⚠️ Unconfirmed, do not assume before re-checking: whether team-shared
  consent changes the 403 outcome; exact rate-limit thresholds; and —
  newly important — **whether a free plan can fetch CSV for non-PB laps at
  all** (`seeTelemetry` is documented as requiring Pro; each lap carries
  `canViewTelemetry`, which `sync` now honours per lap rather than assuming
  either way). Resolved by A28, previously listed here: date-filter param
  names (`after`/`age`) and the `limit` ceiling (1000).

Done per M0b's criteria: this document exists and API capabilities are
enumerated from observed behavior, including the one genuine unknown the
milestone existed to resolve (other-driver lap fetchability).
