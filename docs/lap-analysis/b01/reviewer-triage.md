# Batch B01 — reviewer's triage (half a comparison)

**This is not the comparison.** The reading agent has not run yet. What
follows is the reviewer's own nineteen observations triaged against the sealed
engine output, written after `claude-observations.jsonl` was committed and
pushed (`479a11b`). The reading agent's half, and the agreement matrix that
needs both, come later.

Sealed output regenerates with the Part 2 commands against
`tests/fixtures/spa-blind-2026-07/`.

---

## Both canaries fired

| Canary | Expected | Engine found |
|---|---|---|
| `9XVJTW` | spin | C01 `near_stop+off_track+spin` → `trail_brake_oversteer`, high confidence, min 5 km/h |
| `9PH9M2` | full stop | C15 `near_stop`, min **0 km/h** |
| `QHD9QC` (negative) | uneventful | no incident — and the reviewer reported none |

The canary design works. Two laps the reviewer knew about, one it was expected
to leave alone, all three behaved.

**Two incidents nobody flagged in advance** also exist: `98D9NK` C01
(`near_stop+off_track+spin` → `power_on_oversteer`) and `FS2F1N` C01 (two
`unclassified`). Future batches should draw canaries from the *unflagged* set
so the reviewer's prior knowledge stops being load-bearing.

## The one blind hit

Observation `B01-CLAUDE-002` reported, on a lap the reviewer knew nothing
about, that `98D9NK` C01 goes from brake fully off (row 668) back to maximum
pressure (row 692, brake `1.0`) with the throttle dropping away.

The engine independently detected an incident on that same lap and corner,
`span_start` **751** — about a second *after* the rows the reviewer quoted.

So a blind read of the pedal trace surfaced the same event the incident
detector surfaced, and surfaced it earlier in the lap. Stated carefully: this
is one observation on one lap, not a claim that reading beats detecting. It is
evidence that the method finds real things rather than plausible ones.

## Finding 1 — brake modulation is not counted (CONFIRMED-GAP)

Verified against the engine's own `metrics-report.md` for this corpus, not
only against the source: the sole metric matching `*modulation*` is
**`throttle_modulation_count`**. There is no brake analogue among the
eighteen.

The behaviour is present and corner-specific. Post-release brake
re-applications, by corner, out of eleven laps:

| C01 | C03 | C05 | C07 | C08 | C09 | C15 | C17 | the other ten corners |
|---|---|---|---|---|---|---|---|---|
| 8 | 4 | 9 | 4 | 10 | 7 | 10 | 4 | 0 |

Zero at ten corners and near-universal at five is a pattern, not noise, and it
varies lap to lap at a given corner (0–4 at C01), so it discriminates between
executions rather than describing the track.

**Why `trail_brake_overlap_s` does not already cover it.** That metric
measures *duration* of braking while steering. One long trail-brake and three
separate stabs can produce identical seconds and are completely different
driver inputs. This is precisely the reasoning the engine already accepts on
the throttle side — `throttle_modulation_count` exists *alongside*
`throttle_pickup_dist_pct` and `full_throttle_dist_pct` because timing and
modulation are different questions. The brake side has the timing metrics and
not the modulation one.

**Not an incident artifact.** `X8R0PS` shows the pattern at C08 (rows 6735 and
6921) and has no detected incident at all.

Not acted on. A new metric changes numbers the engine produces, which is a
`docs/SPEC.md` amendment plus a TDD build, deliberately not smuggled in
alongside the protocol that found it.

## Finding 2 — `gear` is masked, not measured (CONFIRMED-GAP, weaker)

`gear` reaches the analysis chain in exactly one place: `segmenter.py:193`,
`active &= lap.gear != 0` — gear-0 spans are *excluded* from corner detection.
No metric, detector, incident rule or model fundamental uses the channel.

So shift behaviour — upshift timing, downshifts under braking, time in
neutral, a missed shift — is entirely unmeasured, and the one place the
channel is consulted throws the samples away.

Worth weighing against A19's own principle, "an off is measured, not filtered
— measure the driver, not the lap": a gear-0 span is a driver action being
filtered. That may still be correct for *segmentation* specifically (a shift
is not a corner landmark) while being a gap at the metric layer. Flagged as a
question, not a defect: the reviewer is not confident enough to call it a bug,
and `confidence: unsure` on `B01-CLAUDE-009` says so.

## The thin-corpus trap, now with evidence

Flagged before the run, and confirmed hard by it. On this corpus the
attribution layer produced:

- **0 shown findings**
- **97 suppression reasons**

Eleven laps across six sessions clears `gates.min_sessions` (2) but not
`gates.min_phase_samples` (10) once a corner is matched in only eight or nine
of them.

This is the engine behaving correctly. It is also exactly the condition in
which a prolific reading agent looks like a discovery machine: nineteen
observations against zero engine findings is a ratio that means nothing.
Scoring rule stands — on a corpus this thin, "engine silent" is **ungated**,
never a coverage gap. Only Findings 1 and 2 survive that rule, and they
survive because they were checked against the *metric list*, which the gates
do not touch.

## Where the reviewer's own read was weak

Nineteen observations from one fully-read slice out of 198
(`claude-read-disclosure.md`). Corners C02–C18 were pattern-scanned for a
single phenomenon, never read. Any observation the reading agent makes outside
C01/C05/C08/C09/C15 is territory the reviewer cannot corroborate in either
direction, and should be treated as uncontested rather than as agreement.

## Status

| Bucket | Count |
|---|---|
| `CONFIRMED-GAP` | 2 (brake modulation; gear unused) |
| `REJECTED-UNGROUNDED` | 0 (19/19 grounded) |
| `REJECTED-KNOWN` | 0 — neither finding is in `answer-key.md` |
| `INSUFFICIENT-DATA` | the seven pedal-overlap and re-application observations, pending the corpus growing |

Pending: the reading agent's half, then the agreement matrix.
