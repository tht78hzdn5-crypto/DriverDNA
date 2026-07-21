# Garage61 API report (M0b)

Probed 2026-07-20 against the live API with a real `GARAGE61_TOKEN`
(scopes granted: `profile`, `openid`, `driving_data`; free subscription
plan). Every fact below is from an observed HTTP response, not
documentation or inference — where a question couldn't be answered from
observed behavior it is marked **unconfirmed**, per the "never assume API
behavior" rule. The token was passed only as an environment variable to a
throwaway probe script for this session; it was never written to disk,
logged, or committed, and no request/response evidence containing it was
saved. Third-party drivers' names encountered while probing shared/team
endpoints are redacted below (`Driver B`, `Driver C`, ...); only the
probing account's own data and structural facts are reported.

## Base URL, versioning, auth

- Base URL: `https://garage61.net/api/v1`
- Auth: `Authorization: Bearer <GARAGE61_TOKEN>` on every request.
- Missing header → `401 {"message": "Missing authorization: supply a
  Bearer token in the Authorization header."}`
- Invalid/garbage token → `401 {"message": "Bad authentication: operation
  Me: security \"OAuth2\": invalid access token."}`
- Every response carries `X-G61-Trace` (a per-request trace id) — worth
  logging on error for support purposes, never as a secret.

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
- **`/laps` exposes only *saved* laps, not the full driven history — one
  per cohort on the probed account.** Census re-run 2026-07-20: iterating
  every cohort from `/me/statistics` and self-filtering, the account's own
  retrievable laps totalled **26 — exactly one per (car, track) cohort**
  (max in any single cohort: 1). Yet `/me/statistics` reports **979 laps
  driven** for the same account (up to 163 in one cohort). So the API
  serves a curated subset (empirically one saved lap per cohort), not
  every lap driven. Observed fact = 1 saved lap/cohort; the *cause* is
  unconfirmed — the account is `subscriptionPlan: "free"` (from `/me`), so
  a free-plan retention/exposure cap is the leading hypothesis, not a
  verified one. **Consequence:** `sync` already pulls everything `/laps`
  returns, so this is a data ceiling, not an under-pull. Anything needing
  many laps *per cohort* — M6's per-cohort trend without the cross-cohort
  bucket-composition confound — is not reachable from this account's API
  contents as they stand; it needs more saved laps per cohort (or a dated
  manual-import path for locally-exported CSVs).

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

## The reference-lap question — resolved for this token

Decision-of-record #2 and the M0b spec both name this the "one genuine
unknown": can this token fetch laps shared by other drivers? **Observed
answer: no.** Other drivers' laps are visible in `/laps` list results
(track/car scoped, not owner-scoped) but their detail and CSV endpoints
return `403 forbidden_lap`. Own-account laps work fully. Per SPEC.md's
already-written contingency ("If other-driver fetch is unavailable,
reference laps degrade to manual-download import tagged `reference`"),
**the reference-lap feature will use the manual `import` path only,
never `sync`**, until/unless a different plan tier or an explicit
sharing relationship is confirmed to change this (untested here).

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

## Capabilities summary → implications for building `sync`

- ✅ Auth, own-lap listing (track/car-scoped + client-side self-filter on
  `driver.id`), single-lap CSV fetch, pagination (`limit`/`offset` +
  `total`) all work and are ready to build on.
- ✅ CSV format from the API matches the manual-download contract
  exactly — the existing `Garage61Parser` needs no format changes to
  accept API-sourced CSVs.
- ❌ Other-driver ("reference") lap fetch is **not available** with this
  token — reference laps stay on the manual `import` path,
  `role=reference`, as already specified.
- ⚠️ `sync` must discover cohorts via `/me/statistics` (or a
  driver-supplied car/track list) and loop `/laps?tracks=...&cars=...`
  per cohort — there is no unscoped "give me everything" call.
- ⚠️ `/laps` returns only *saved* laps — observed as **one per cohort** on
  the probed (free-plan) account, vs 979 laps driven. `sync` pulls all of
  them, so it's a data ceiling, not an under-pull: M6's per-cohort trend
  can't be fed from this account's API contents until more laps are saved
  per cohort (leading hypothesis: a free-plan cap — unconfirmed) or a
  dated manual-import path is added for locally-exported CSVs.
- ⚠️ Unconfirmed, do not assume before re-checking: the real query-param
  names for date-range and team/account-scoped filtering; the exact
  `limit` ceiling; whether team-shared consent changes the 403 outcome;
  exact rate-limit thresholds.

Done per M0b's criteria: this document exists and API capabilities are
enumerated from observed behavior, including the one genuine unknown the
milestone existed to resolve (other-driver lap fetchability).
