# Batch B01 — pre-registered answer key

**Written before any lap slice was read.** Corpus:
`tests/fixtures/spa-blind-2026-07/` (11 GR86/Spa laps, 6 sessions, 18 corners).

This file exists so the reviewer cannot retro-fit a verdict. Everything below
was derived from reading the *source code and specs* — never the traces — and
is committed ahead of the reading. An observation that lands on one of these
is calibration evidence (the reader works), not a discovery. An observation
that lands somewhere else is a candidate.

---

## Known weak spots in the engine's analysis layer

Ten, from `docs/SPEC.md`, module docstrings, and the code itself. Numbered so
the comparison can cite them.

**K1 — `classify.py`'s ordered if/elif attributes a kerb strike to the driver.**
The `external` (kerb/bump) branch runs *after* every oversteer branch, so a
spin triggered by a kerb is classified `trail_brake_oversteer` or similar if
the pedal signature happens to match first. `src/driverdna/incidents/classify.py:50-82`.

**K2 — throttle-pickup falls back to `argmin` on a corner with no lift.**
When the driver never drops below `throttle_pickup_level`, the pickup landmark
becomes the minimum of throttle within a bounded window, which on a flat trace
is essentially arbitrary. `src/driverdna/corners/segmenter.py:129-152`.

**K3 — `coast_s` clamps negatives to zero.** `coast_s = max(0, pickup - release)`
hides the case where throttle arrives *before* the brake is off — pedal overlap
at that boundary reads as "no coast" rather than as overlap.
`src/driverdna/metrics/technique.py:150`.

**K4 — no detector for entry speed, braking-point consistency, or line/apex
placement**, despite `min_speed_kmh`, `brake_point_dist_pct` and
`apex_dist_pct` all existing as metrics. Five detectors exist; none covers
these three.

**K5 — `same_lap_twice` pools per-corner CV across metric types without
normalization.** A "% lap" metric's natural CV (~0.007) and a count metric's
(~0.99) go into one flat average. M6's sibling bug was fixed by per-unit
normalization (SPEC A21); the coaching path was deliberately left unfixed and
is still open. `src/driverdna/config.py:560`, `docs/SPEC.md:731-746`.

**K6 — heel-toe blips cannot be separated from brake dragging** without RPM
correlation; `overlap_max_s` accommodates typical heel-toe and needs retuning
per car. `src/driverdna/config.py:189-197`.

**K7 — `near_stop_speed_kmh` (25 km/h) is track-specific** and would misfire on
a track with genuine sub-25 km/h corners. `src/driverdna/config.py:300-306`.

**K8 — no lap-validity channel exists**, so incident and outlier handling is
statistical (median ± k·MAD) and counted, never authoritative.

**K9 — a phase window can be undefined by design.** Zero span (flat kink) or a
span over half a lap (inverted landmarks) yields `None`, which is a legitimate
driving style, not an error. `src/driverdna/attribution/engine.py:79-84`.

**K10 — tire slip/utilization and vision/eye-line are permanently
unmeasurable** from this channel set and are never inferred.

---

## Reviewer contamination — disclosed, not hidden

My own read of this batch is **not fully blind**, and pretending otherwise
would defeat the point of the seal. Before any lap was read, I already knew
from planning research:

- `9XVJTW` contains a spin, associated with La Source;
- `9PH9M2` contains a near-stop/full stop, associated with the Bus Stop.

I did **not** know, and have not looked at, any engine metric, finding,
baseline, coaching output, or attribution result for this corpus, nor anything
about the other nine laps.

Consequence, applied in the comparison: **any observation I make about an
incident on `9XVJTW` or `9PH9M2` is excluded from the agreement count.** It is
not independent evidence. The other nine laps, and every non-incident
observation on those two, stand normally.

This is a flaw in the protocol as first written, not just in this run: the
reviewer has to be blinded *when the batch is designed*, not only when it is
read. Recorded in `docs/LAP-ANALYSIS-PROTOCOL.md`'s limitations, and the fix
for future batches is that whoever picks the canaries is not the reviewer.

---

## Canaries for this batch

- **Positive:** `9XVJTW` (spin), `9PH9M2` (full stop). Missing both discards
  the batch unread; missing one drops every observation a confidence tier.
- **Negative:** `QHD9QC` — the fastest lap in the corpus at 171.15 s and, per
  the fixture manifest, unremarkable. A confident report of a major event here
  counts against precision.
