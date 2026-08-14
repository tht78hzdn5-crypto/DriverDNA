# DriverDNA report — owner / GR86 @ Spa-Francorchamps

Laps: 11 · sessions: 3 · payload v8. Grouped by racing fundamental; sources are never blended, and every finding keeps its own source tag, N, spread, and evidence IDs.

## Findings

### Braking

| source | finding | s | n | spread | evidence |
|---|---|---|---|---|---|
| vs-self | C05 entry: 0.105 s between your fastest and slowest laps | 0.105 | 11 | 0.072 | 11 refs |
| vs-self | C14 entry: 0.204 s between your fastest and slowest laps | 0.204 | 11 | 0.138 | 11 refs |

### Rotation

> **Settle the entry, then one committed input to the apex.**
>
> Every extra steering correction between turn-in and apex is the car negotiating a line you haven't committed to — each one scrubs speed the corner didn't need to lose.
>
> _Try this:_ Next session: pick your turn-in point before the corner and commit to a single steering input. Ignore lap time; count your own corrections.

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

> **Pick up later but build smoothly; if you have to lift, you opened it too early.**
>
> A lift after picking up throttle means the pickup point was a guess, not a commitment — the car had to give back grip mid-application it never should have been asked for.
>
> _Try this:_ Next session: delay throttle pickup slightly and apply it as one continuous build to full throttle — no stabs, no lifts.

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
