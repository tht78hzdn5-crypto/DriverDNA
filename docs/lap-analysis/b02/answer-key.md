# Batch B02 — pre-registered answer key

**Written after grounding ran, before any comparison.** Corpus:
real synced laps from `scratch\g61_test_batch\blind` — the owner's own DB
(not committed fixtures). Two car/track cohorts:
- **Spa / GR86**: 4 laps, 14 corners each (lap IDs `01KYRBQYPSPQ9R677BVPQG4C2C`,
  `01KYRD14VM3KM8MEF8XYNDGATC`, `01KYRD14VM3KM8MEF8XXSN4W6Z`,
  `01KYRD14VM3KM8MEF8XYNV00HE`).
- **Summit Point / Mustang GT4**: 12 laps, 8 corners each (lap IDs
  `01KYK1B9DDH1W4JJKS…` × 12).

Total: 183 grounded observations, 0 rejected (`grounding-gemini.md`).

This file exists so the comparison cannot retro-fit "we knew that" after the
fact. Everything below is derived from reading the **source code and specs**,
not the traces. An observation that lands on one of these is calibration;
an observation elsewhere is a candidate.

---

## Seal order — disclosed, not hidden

The protocol requires the reviewer (Claude) to commit their own blind observations
*before* the reading agent runs. That did not happen for B02. The CCR session
tasked with this work (`claude/gemini-observation-grounding-rbz8vl`) was created
*after* Gemini ran and produced the grounding report.

Consequence: **there is no independent reviewer read for B02.** The comparison
matrix that normally occupies the bottom-right cells (both readers agree / engine
silent → coverage-gap candidate) is missing one column. Gemini's observations
can still be triaged against the sealed engine output and this answer key, but
the corroboration signal the protocol relies on is absent.

The digest files are not in this repository (they are real laps, not committed
fixtures), so this is unrecoverable for B02. Recorded rather than papered over.

---

## Known weaknesses — carried forward from B01 + new

B01's K1–K10 are restated here. K11 and K12 are the two confirmed gaps B01
itself found; they are now *known* for the purpose of this batch's comparison.

**K1 — `classify.py`'s `external` branch runs after every oversteer branch.**
A spin on a kerb whose brake pressure happened to exceed `classify_brake_floor`
at onset is classified `trail_brake_oversteer` (high confidence), not `external`.
`src/driverdna/incidents/classify.py:50–80`.

**K2 — throttle pickup falls back to `argmin` on a corner with no lift.**
`throttle_pickup_dist_pct` and `coast_s` are both downstream of a landmark that
becomes the minimum of throttle within a bounded window when the driver never
drops below `throttle_pickup_level`. On a flat trace that is essentially
arbitrary. `src/driverdna/corners/segmenter.py:129–152`.

**K3 — `coast_s` clamps negatives to zero.**
`coast_s = max(0, pickup - release)` hides pedal overlap at the
brake-release/throttle-pickup boundary — simultaneous pedals reads as "no coast"
rather than as overlap.
`src/driverdna/metrics/technique.py:150`.

**K4 — no detector for entry speed, braking-point consistency, or apex
placement**, despite `min_speed_kmh`, `brake_point_dist_pct`, and
`apex_dist_pct` existing as metrics. Five principle detectors exist; none covers
these three. `src/driverdna/metrics/detectors.py`.

**K5 — `same_lap_twice` pools per-corner CV without unit normalization.**
The coaching gate for in-lap consistency (`coaching/engine.py`) pools per-corner
coefficient-of-variation across metric types: a "% lap" metric's naturally tiny
CV and a "count" metric's naturally large CV enter a flat average. The M6 sibling
was fixed (A21, `dm-v2`); the coaching gate was deliberately left open.
`src/driverdna/coaching/engine.py`.

**K6 — heel-toe blips are indistinguishable from brake dragging** without RPM
correlation. `overlap_max_s` is calibrated for typical heel-toe timing and would
need tuning per car. `src/driverdna/config.py:189–197`.

**K7 — `near_stop_speed_kmh` (25 km/h) is track-specific.** A track with genuine
sub-25 km/h corners would trigger a false near-stop.
`src/driverdna/config.py:300–306`.

**K8 — no lap-validity channel exists.** Incident and outlier handling is
statistical (`median ± k·MAD`) and counted, never authoritative.

**K9 — a phase window can be undefined by design.** Zero span (flat kink) or an
inverted-landmarks corner yields `None` — a legitimate driving style, not an
error. `src/driverdna/attribution/engine.py:79–84`.

**K10 — tire slip/utilization and vision are permanently unmeasurable** from this
channel set and are never inferred.

**K11 — `brake_modulation_count` does not exist (CONFIRMED-GAP, B01 Finding 1).**
The engine counts `throttle_modulation_count` (lifts/stabs after pickup) but has
no brake analogue. Post-release brake re-applications — present and
corner-specific in the Spa corpus (8/11 laps at C01, near-universal at C08/C09) —
are invisible to the engine. B01 confirms this is real signal, not noise.

**K12 — `gear` channel is masked, not measured (CONFIRMED-GAP, B01 Finding 2).**
`gear` reaches the analysis chain once, at `segmenter.py:193`, where gear-0 spans
are *excluded* from corner detection. No metric, detector, incident rule, or model
fundamental uses the channel. Shift timing, missed shifts, downshifts under
braking, and time in neutral are entirely unmeasured.

---

## Corpus notes for triage

**Spa / GR86 laps** — same circuit and car as B01; K1–K12 apply. The four laps
here are not the committed `spa-blind-2026-07/` fixtures, so prior engine output
(B01's sealed reports) is not directly comparable. Generate fresh sealed output
for this corpus before triaging.

**Summit Point / Mustang GT4 laps** — new car/track combination not seen in B01.
Eight corners. The Mustang GT4 carries more power than the GR86 at corner exit,
so K1's power-on-oversteer path and K3's overlap-at-pickup region are worth
attention. K6 (heel-toe discrimination) applies to the Mustang's sequential
gearbox under braking. No prior engine output exists for this cohort in any
committed document.

**Thin corpus at triage time.** The `driverdna census` output for this corpus
(if generated) is the authoritative read on whether the gates fire. An agent
reading 12 laps across what may be several sessions could easily produce a ratio
of prolific-reading to quiet-engine that the protocol warns against
(see B01's `reviewer-triage.md`, "The thin-corpus trap"). Score "engine silent"
as **ungated** where gate suppression is the plausible reason, not a coverage gap.
