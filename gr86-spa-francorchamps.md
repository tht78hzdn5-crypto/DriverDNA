# DriverDNA report — owner / GR86 @ Spa-Francorchamps

Laps: 11 · sessions: 3 · payload v13. Grouped by racing fundamental; sources are never blended, and every finding keeps its own source tag, N, spread, and evidence IDs.

## Summary

11 laps across 3 sessions at GR86 @ Spa-Francorchamps. Best lap 2:51.250.

Most of the typical loss sits in the mid-corner phase (1.688 s/lap). Medium corners carry the largest share (1.668 s/lap). There is no reference comparison for this cohort.

> **You're a passenger in the coasting zone. The car must always be working—either braking, turning, or driving.**

## Findings

### Braking

| source | finding | s | n | spread | evidence |
|---|---|---|---|---|---|
| vs-self | C05 entry: 0.105 s between your fastest and slowest laps | 0.105 | 11 | 0.072 | 11 refs |
| vs-self | C14 entry: 0.204 s between your fastest and slowest laps | 0.204 | 11 | 0.138 | 11 refs |

### Rotation

> **You're a passenger in the coasting zone. The car must always be working—either braking, turning, or driving.**
>
> Neither pedal working means neither axle is doing anything useful — the car coasts through time that braking, turning, or driving could have used.
>
> _Try this:_ Next session: find where you're on neither pedal mid-corner and close that gap by a fraction — brake a touch later or pick up throttle a touch sooner.

| source | finding | s | n | spread | evidence |
|---|---|---|---|---|---|
| vs-self | C01 mid-corner: 0.234 s between your fastest and slowest laps | 0.234 | 11 | 0.205 | 11 refs |
| vs-self | C05 mid-corner: 0.182 s between your fastest and slowest laps | 0.182 | 11 | 0.101 | 11 refs |
| vs-principle | C01: extra steering corrections on 6 of 11 laps | — | 11 | — | 6 refs |
| vs-principle | C02: extra steering corrections on 9 of 10 laps | — | 10 | — | 9 refs |
| vs-principle | C05: coasting mid-corner on 11 of 11 laps | — | 11 | — | 11 refs |
| vs-principle | C14: coasting mid-corner on 11 of 11 laps | — | 11 | — | 11 refs |
| vs-principle | C14: extra steering corrections on 6 of 11 laps | — | 11 | — | 6 refs |

### Corner exit

> **You're stabbing at the throttle on exit instead of squeezing it on. Feed it in once, progressively, from pickup to full throttle — every lift in between costs drive.**
>
> The throttle is a commitment, not a question. Each lift-and-stab between pickup and full throttle unloads the rear, then asks it to take load again — the car never settles, and the exit speed that should carry down the straight is spent managing the weight transfer instead. One progressive squeeze lets the rear load once and stay loaded.
>
> _Try this:_ Next session: on one corner, count your throttle applications out loud. It should be one. If you lift mid-exit, you picked the throttle up too early — wait for the car to settle, then commit.

| source | finding | s | n | spread | evidence |
|---|---|---|---|---|---|
| vs-self | C03 exit: 0.115 s between your fastest and slowest laps | 0.115 | 11 | 0.248 | 11 refs |
| vs-self | C05 exit: 0.053 s between your fastest and slowest laps | 0.053 | 11 | 0.049 | 11 refs |
| vs-self | C08 exit: 0.205 s between your fastest and slowest laps | 0.205 | 10 | 0.162 | 10 refs |
| vs-self | C10 exit: 0.145 s between your fastest and slowest laps | 0.145 | 11 | 0.168 | 11 refs |
| vs-principle | C01: lifting after throttle pickup on 7 of 11 laps | — | 11 | — | 7 refs |
| vs-principle | C10: lifting after throttle pickup on 6 of 11 laps | — | 11 | — | 6 refs |

### Consistency

> **Match a lap before you try to beat it — repeatability comes before pace.**
>
> A technique that varies lap to lap isn't a technique yet — it's a range of outcomes. Pace built on an inconsistent input is pace you can't reliably reproduce under pressure.
>
> _Try this:_ Next session: try to execute this corner exactly the same way three laps in a row. Ignore lap time; judge yourself only on how close the three felt.

_No finding clears the evidence gates here yet._


Suppressed findings: 91 (each with its stated reason — see the JSON report for the full list).

## Cumulative typical loss (s/lap vs robust baseline)

| by phase | s |
|---|---|
| entry | 0.613 |
| exit | 1.057 |
| mid | 1.688 |

| by class | s |
|---|---|
| fast | 0.195 |
| medium | 1.668 |
| slow | 1.495 |

## Corner map

| corner | class | apex (% lap) |
|---|---|---|
| C01 | slow | 5.6 |
| C02 | fast | 19.2 |
| C03 | medium | 34.7 |
| C04 | medium | 37.8 |
| C05 | slow | 43.9 |
| C06 | medium | 46.8 |
| C07 | medium | 55.4 |
| C08 | medium | 56.8 |
| C09 | medium | 66.8 |
| C10 | medium | 70.1 |
| C11 | medium | 72.7 |
| C12 | fast | 84.0 |
| C13 | fast | 89.6 |
| C14 | slow | 97.3 |
| C15 | medium | 75.8 |
| C16 | fast | 87.8 |

## Data quality

Flag counts: {'clipped_pedal': 11} · laps with flags: 11/11

## Not measured (never inferred)

- tire slip/utilization — no slip channel in the source; never inferred
- vision/eye-line — not measurable from telemetry; never inferred
- fuel load, weather, lap validity, stint index — absent from the source contract; controls degrade with stated caveats instead

## Caveats

- lap validity has no source channel: statistical outlier screening with counts, never silent exclusion
