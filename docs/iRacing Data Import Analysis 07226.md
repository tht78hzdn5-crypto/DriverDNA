# iRacing Data Import Analysis

**Date:** 2026-07-26
**Question asked (owner):** Can we import data right from iRacing in our current
configuration?
**Short answer:** No. And after investigation, the recommendation is not to
build it yet — owner concurred and declined on 2026-07-26 21:50 UTC (§8).

**Sourcing note.** §1–§5 are established from this repository at commit `64fe1ba`;
every file:line reference resolves there. §6 is compiled from iRacing's published
documentation and support articles on 2026-07-26 and is **not** probe-verified —
unlike `docs/garage61-api.md`, which was generated from a live API probe with a
real token. We hold no iRacing credentials and cannot obtain any (§6), so no
claim in §6 has been observed first-hand. Treat it accordingly, and re-verify
before acting on it.

---

## 1. Current state: no direct iRacing import exists

There is no iRacing-specific code in the repository. The complete inventory of
iRacing mentions is prose and one comment:

- `README.md:3`, `docs/PROJECT-BRIEF.md:20` — "Garage61 lap exports (iRacing)"
- `src/driverdna/config.py:291` — `offtrack_position_value` described as
  "(iRacing TrackSurface; 3=on-track, 4=off)"
- `docs/garage61-api.md:92` — Garage61 integer IDs are not iRacing `platform_id`
  strings
- `tests/fixtures/manifest.toml:11` — car/track strings are "not authoritative
  iRacing names"

No `.ibt` handling, no `irsdk`/`pyirsdk` dependency, no telemetry-format adapter
abstraction of any kind.

All three ingest paths converge on one Garage61 CSV reader:

| Path | Entry | Reader |
|---|---|---|
| `driverdna import` | `cli.py:78-195` (globs `*.csv` at `cli.py:126`) | `parse_lap` — `ingest/parser.py:188` |
| `driverdna sync` | `garage61/sync.py:117-138` | `parse_lap_text` — `ingest/parser.py:206` |
| `POST /api/laps/upload` | `ui/api.py:307` | same `import_lap_file` |

Format knowledge lives in literal string constants (`ingest/contract.py:22-41`)
and hardcoded filename regexes (`parser.py:59`, `parser.py:69-72`). There is no
dialect layer, registry, or dispatch.

## 2. Why the gap is smaller than it looks: the contract is already iRacing data

`EXPECTED_HEADER` (`ingest/contract.py:22-41`) is essentially a passthrough of
iRacing SDK variable names, and every unit matches iRacing natively:

```
Speed, LapDistPct, Lat, Lon, Brake, Throttle, RPM, SteeringWheelAngle,
Gear, Clutch, ABSActive, DRSActive, LatAccel, LongAccel, VertAccel,
Yaw, YawRate, PositionType
```

- `Speed` m/s; `SteeringWheelAngle` **radians** (converted to degrees at
  `parser.py:312`); `Lat`/`LongAccel`/`VertAccel` m/s²; `Yaw` rad; `YawRate`
  rad/s; `Lat`/`Lon` real GPS degrees.
- Known renames Garage61 applies: `PlayerTrackSurface` → `PositionType`;
  `ABSActive`/`DRSActive` rendered as string booleans `"true"`/`"false"`
  (`parser.py:172-176`).

So mapping a real `.ibt` to the engine is a rename table, not a unit conversion.
That is the single most important finding here — it is why this is a bounded
piece of work rather than a new-format project.

## 3. The five real obstacles

1. **`.ibt` is binary and multi-lap.** Garage61 delivers one clean lap per file.
   An `.ibt` is a whole session and would need splitting on `Lap`/`LapDistPct`
   wraps — which the parser today *flags as bad* rather than splits
   (`unexpected_wrap_count`, `parser.py:277-280`).

2. **60 Hz is assumed globally and never measured.** `SAMPLE_RATE_HZ = 60`
   (`contract.py:20`) is imported directly by `corners/segmenter.py`,
   `metrics/technique.py`, `metrics/detectors.py`, `incidents/detector.py`,
   `incidents/classify.py`, and implicitly by `signals.py`'s sample-count
   smoothing window. There is **no time column at all**; `elapsed_s` and
   `duration_s` are fabricated from the row index (`parser.py:302-303`). An
   `.ibt` carries a real `tickRate` in its header — an improvement, since it
   permits validation instead of assumption — but today a non-60 Hz file would
   produce silently wrong lap times, window durations and thresholds
   everywhere, with nothing detecting it.

3. **The M0a negative contract collides.** `FORBIDDEN_COLUMN_NAMES`
   (`contract.py:46-70`) locks `Fuel*`, `AirTemp`/`TrackTemp`/weather,
   `OnPitRoad`, `SessionNum`/`SessionTime`, `LapCompleted`/`LapValid`, `Stint`,
   `Run` and `PlayerTrackSurface` as *confirmed absent*. An `.ibt` has all of
   them. This is not a bug — the lock is correctly scoped to the Garage61 export
   — but it means an `.ibt` source needs **its own documented M0a-style source
   contract**, generated from observed evidence, never a quiet widening of the
   existing one.

4. **Live capture is structurally out of reach in this environment.** iRacing's
   live SDK is Windows shared memory; the development environment is Linux.
   Only the `.ibt` files the sim writes to `Documents\iRacing\telemetry\` are
   portable.

5. **No dependency exists for it.** `pyirsdk` is absent from
   `pyproject.toml:12-18` and not installed. Project precedent (`sync` used
   stdlib `urllib` rather than adding `requests`) favours a small stdlib
   `struct` reader over a vendored or added dependency.

## 4. The correct seam, already proven twice

`_parse_rows` (`parser.py:224-324`) is format-neutral, and `import_parsed_lap`
(`pipeline.py:83`) takes a `TelemetryLap` plus metadata and knows nothing about
CSVs — `garage61/sync.py:132-138` already calls it directly, and `parse_lap_text`
(`parser.py:206-221`) already exists as a non-file-path sibling of `parse_lap`.

An `.ibt` reader plugs in there without touching the engine.

Dispatching on file extension inside `import_lap_file` (`pipeline.py:75`) is the
**wrong** seam: it puts format knowledge in the pipeline and still requires
changing `cli.py:126`'s `*.csv` glob.

Constraints any new source must satisfy: produce all 20 `_BLOB_CHANNELS` field
names (`db.py:43-48`), or content-hashing (`db.py:252-262`) and the blob
round-trip break; resample to 60 Hz or accept silently wrong timings; populate
`source_path` uniquely, since `db.py:629-631` dedups on `source_file` as a
string.

## 5. What an `.ibt` path would gain

Real `SessionTime` timestamps make `lap_date`, `session_key` and `run_index`
derivable at import — metadata the manual CSV path cannot produce today
(`run_index` is currently API-only, `sync.py:135`). `lap_date` is M6 trend's
precondition, and the absence of a per-cohort dated history is exactly what
forced dated manual import (`--date`) into existence.

## 6. iRacing API access — what "Login with iRacing" actually is

This is the flow seen on Garage61 and similar apps. **Critical finding: it would
not give us telemetry.**

**It is OAuth 2.0 / 2.1.** iRacing runs an OAuth service at `oauth.iracing.com`.
The user is redirected to iRacing's own login page and back; the third party
never sees the password. This replaced "legacy read-only authentication" (email +
`SHA256(password + lowercased_email)`, base64, against
`members-ng.iracing.com/data/auth`), **retired 2025-12-09**. Any guide describing
that password hash is obsolete.

Mechanics, per iRacing's documentation:

- **`/authorize`** — `client_id`, `redirect_uri` (must match the registered value
  exactly), `response_type=code`. PKCE (`code_challenge`, `S256` recommended) is
  **required** for clients that cannot reasonably keep a secret, and encouraged
  otherwise. The only scope named in the docs is `iracing.auth`.
- **`/token`** — three grants: **authorization code** (distributed apps),
  **refresh token** (single-use — a refresh token may be used exactly once), and
  a **password limited grant**, an in-house OAuth 2.1 extension for headless
  server-side clients where only the registered user can use it. Access tokens
  are short-lived (doc example 600 s); refresh tokens ~7 days (604800 s).
- **Client secret**, where issued, must be **masked** before transmission
  (SHA-256 + base64; the server re-hashes what it receives). Reference
  implementations exist in Python.
- The password limited grant is aggressively rate-limited
  (`RateLimit-Limit`/`Remaining`/`Reset`; `400` plus `Retry-After` on
  exceedance).

### Two blockers, either fatal alone

1. **The API carries no telemetry.** iRacing's own support page states it
   plainly: *"the /data API endpoint is NOT the same API as used by the sim for
   local telemetry logging, also referred to as the iRacing SDK."* The `/data`
   API serves results, subsessions, lap *chart/time* data, standings, career
   stats, cars and tracks — **not** the sampled channels (`Speed`, `Brake`,
   `Throttle`, `SteeringWheelAngle`, `Lat`/`Lon`, `Yaw`, accelerations) that
   every DriverDNA metric, corner segment, detector and incident is computed
   from. Every channel in `EXPECTED_HEADER` would still be missing.

   This is why Garage61, Braking Lab and the rest all ship a **Windows desktop
   capture client** that watches `Documents\iRacing\telemetry\` for `.ibt` files
   (or reads the live SDK) and uploads them. The web login is identity; the
   desktop agent is the telemetry. Garage61's CSV export is the far end of that
   pipe — which is exactly what DriverDNA already consumes.

2. **Registration is closed.** *"We have paused the creation of OAuth client IDs
   while we evaluate existing 3rd party usage of iRacing's APIs and SDK."* No
   `client_id` is obtainable at all right now; reopening will be announced via
   iRacing's forums and release notes.

### Conclusion for DriverDNA

iRacing API access is neither sufficient nor currently available, and pursuing
it would not move telemetry ingest forward by one channel. The only paths to
real iRacing telemetry remain (a) reading `.ibt` files, or (b) the live SDK.
Everything in §1–§5 stands unchanged.

A *separate*, smaller opportunity, noted but not pursued: if registration
reopens, `/data` could enrich lap **metadata** — authoritative car/track names
(replacing the filename-derived labels `parse_garage61_filename` guesses at,
`parser.py:75-89`), session and subsession identity for
`session_key`/`run_index`, and official lap times as a cross-check. Useful, not
load-bearing, gated on a paused registration.

### Sources (§6)

- OAuth client credentials, registration paused —
  <https://support.iracing.com/support/solutions/articles/31000177790-oauth-client-credentials>
- Auth Service introduction —
  <https://oauth.iracing.com/oauth2/book/introduction.html>
- `/authorize` endpoint —
  <https://oauth.iracing.com/oauth2/book/authorize_endpoint.html>
- `/token` endpoint —
  <https://oauth.iracing.com/oauth2/book/token_endpoint.html>
- Legacy read-only authentication —
  <https://support.iracing.com/support/solutions/articles/31000173894-enabling-or-disabling-legacy-read-only-authentication>

## 7. Owner preference recorded for future work

If/when built, extra iRacing channels (fuel, weather, `OnPitRoad`) are to be
**stored**, not discarded — owner preference registered 2026-07-26.

Consequence, stated honestly alongside the preference: this widens
`_BLOB_CHANNELS` (`db.py:43-48`), which is also the input to `_content_hash`
(`db.py:252-262`) — so it changes the dedup hash and the blob format, and needs
a migration plus an explicit decision about byte-identity with existing laps.

Adopting iRacing's `LapValid`/`OnPitRoad` as *engine inputs* is a separate,
larger decision (today lap validity is outlier-flagging only) and is explicitly
**not** implied by storing them.

## 8. Recommendation and decision

**Assessment: not worth building at this time.** This is analysis offered as a
recommendation, not a finding; the facts it rests on are §1–§6 above.

### The case for building it

Real, and not to be dismissed. The `.ibt` route removes a third party from the
middle of the only pipe that feeds the entire instrument. It would end the
dependence on Garage61's export filename shape — already flagged as fragile at
`parser.py:64-67` and in `docs/garage61-api.md` — and on an API that caps
`/laps` at roughly one saved lap per driver per cohort, the exact limitation
that forced dated manual import into existence. It would also deliver metadata
the manual path structurally cannot (§5). For a tool whose whole thesis is a
persistent Driver Model built over time, owning the intake is strategically the
right end state.

### The case against it, now

The cost is concentrated in the places this codebase can least afford to
disturb, and the payoff is duplicative:

1. **It reopens M0a.** The source contract is *locked* — that lock is the
   foundation everything above it was built on, and `FORBIDDEN_COLUMN_NAMES`
   makes the absence of fuel/weather/`OnPitRoad`/`LapValid` a tested guarantee.
   Combined with the decision to store the extra channels (§7), this widens
   `_BLOB_CHANNELS`, which is also the `_content_hash` input — changing the
   dedup key and blob format, requiring a migration, and forcing an explicit
   ruling on byte-identity with every lap already imported. Determinism is
   currently verified mechanically by byte-diffing artifacts across runs; that
   proof must be re-established, not assumed.

2. **Session-splitting is new engine behaviour, not new plumbing.** Every lap in
   the system to date arrived pre-cut by Garage61. Splitting a session on
   `LapDistPct` wraps means the parser must now *produce* lap boundaries it
   currently only validates — and `unexpected_wrap_count` exists precisely to
   reject multi-lap files. Out-lap, in-lap, pit and tow handling all become
   decisions the engine has never had to make. That is where the real bugs would
   live, and they would be quiet ones: wrong boundaries produce plausible
   numbers.

3. **`SAMPLE_RATE_HZ = 60` is load-bearing and unguarded.** Reading a real
   `tickRate` is an improvement, but it means the ingest path must enforce
   something nothing currently checks — and enforcement has to be right the
   first time, because a rate mismatch is silently wrong *everywhere* rather
   than loudly wrong somewhere.

4. **The API half is unavailable and wouldn't help anyway.** OAuth client-ID
   registration is paused, and `/data` carries no telemetry channels at all
   (§6). The "log in with iRacing like Garage61 does" shape people picture is
   not on the table, and building toward it would not advance telemetry ingest
   by one channel.

5. **The current path works.** `sync` is live-verified against the owner's real
   account; manual and browser import both auto-detect car/track; dated import
   closes the trend gap. Nothing measured today is blocked on this. The honest
   framing is that `.ibt` import buys *independence and richer metadata*, not
   new capability — and independence is worth most when the dependency is
   actually failing, which it is not.

### Sequencing view

If this is built, the right trigger is a Garage61 disruption (export format
change, API restriction, service outage) or a concrete analysis that genuinely
requires a channel or metadata field only `.ibt` carries. Absent either, the
effort is better spent on the engine and Driver Model layers, where the
constitution says the product actually lives. Should it become necessary, §4
identifies the correct seam and the work is bounded and well understood — this
is a deferral, not an abandonment, and nothing in the current design forecloses
it.

### Owner decision

**2026-07-26, 21:50 UTC — no.** The owner independently and explicitly declined
iRacing integration at the scope discussed here (native `.ibt` import and/or
iRacing API access) at this time.

Recorded per CLAUDE.md's decision discipline so the decision and its date are
durable rather than living only in chat. Revisit on one of the triggers named
above; the stored-extra-channels preference in §7 stands as pre-registered
intent for that day.

### Scope of this document

This records a finding and a deferral. It refines none of the nine philosophy
points and changes no out-of-scope item. No engine behaviour, contract, or
threshold is altered by it: no `.ibt` reader, no new dependency, no change to
`contract.py`, `SAMPLE_RATE_HZ`, `_BLOB_CHANNELS`, or any ingest path.
