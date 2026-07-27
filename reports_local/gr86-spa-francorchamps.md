# DriverDNA report — owner / GR86 @ Spa-Francorchamps

Laps: 11 · sessions: 6 · payload v4. Sources are never blended; findings carry N, spread, source tag, and evidence IDs.

## Findings

| source | finding | s | n | spread | status | evidence |
|---|---|---|---|---|---|---|
| vs-self | C01 mid: slower laps lose 0.821 s here vs faster laps | 0.821 | 11 | 0.416 | shown | 11 refs |
| vs-self | C06 entry: slower laps lose 0.064 s here vs faster laps | 0.064 | 11 | 0.034 | shown | 11 refs |
| vs-self | C06 exit: slower laps lose 0.091 s here vs faster laps | 0.091 | 11 | 0.073 | shown | 11 refs |
| vs-self | C08 entry: slower laps lose 0.061 s here vs faster laps | 0.061 | 10 | 0.063 | shown | 10 refs |
| vs-self | C08 mid: slower laps lose 0.071 s here vs faster laps | 0.071 | 10 | 0.060 | shown | 10 refs |
| vs-self | C15 entry: slower laps lose 0.079 s here vs faster laps | 0.079 | 11 | 0.137 | shown | 11 refs |
| vs-self | C15 exit: slower laps lose 0.142 s here vs faster laps | 0.142 | 11 | 0.301 | shown | 11 refs |
| vs-principle | C01: coast-window on 6/10 laps. Between brake release and throttle pickup the car should be working, not coasting; 3.63 s with neither pedal is time the corner gives nobody. | — | 10 | — | shown | 6 refs |
| vs-principle | C01: one-steering-input on 5/10 laps. One committed steering input entry to apex; 3 correction(s) beyond the jitter floor suggest the entry (speed, line, or vision) wasn't settled. | — | 10 | — | shown | 5 refs |
| vs-principle | C01: throttle-brake-overlap on 6/11 laps. Throttle and brake should not work against each other; 2.40 s of overlap in this corner wastes both. | — | 11 | — | shown | 6 refs |
| vs-principle | C02: one-steering-input on 9/10 laps. One committed steering input entry to apex; 14 correction(s) beyond the jitter floor suggest the entry (speed, line, or vision) wasn't settled. | — | 10 | — | shown | 9 refs |
| vs-principle | C03: coast-window on 7/10 laps. Between brake release and throttle pickup the car should be working, not coasting; 1.67 s with neither pedal is time the corner gives nobody. | — | 10 | — | shown | 7 refs |
| vs-principle | C03: one-steering-input on 5/10 laps. One committed steering input entry to apex; 3 correction(s) beyond the jitter floor suggest the entry (speed, line, or vision) wasn't settled. | — | 10 | — | shown | 5 refs |
| vs-principle | C03: throttle-monotonic on 5/10 laps. Once picked up, throttle should build monotonically to full; 1 lift(s)/stab(s) before full throttle mean the pickup came earlier than the car could take. | — | 10 | — | shown | 5 refs |
| vs-principle | C05: coast-window on 10/11 laps. Between brake release and throttle pickup the car should be working, not coasting; 4.03 s with neither pedal is time the corner gives nobody. | — | 11 | — | shown | 10 refs |
| vs-principle | C06: one-steering-input on 8/11 laps. One committed steering input entry to apex; 6 correction(s) beyond the jitter floor suggest the entry (speed, line, or vision) wasn't settled. | — | 11 | — | shown | 8 refs |
| vs-principle | C08: coast-window on 9/10 laps. Between brake release and throttle pickup the car should be working, not coasting; 6.68 s with neither pedal is time the corner gives nobody. | — | 10 | — | shown | 9 refs |
| vs-principle | C08: one-steering-input on 7/10 laps. One committed steering input entry to apex; 2 correction(s) beyond the jitter floor suggest the entry (speed, line, or vision) wasn't settled. | — | 10 | — | shown | 7 refs |
| vs-principle | C15: coast-window on 11/11 laps. Between brake release and throttle pickup the car should be working, not coasting; 3.83 s with neither pedal is time the corner gives nobody. | — | 11 | — | shown | 11 refs |
| vs-principle | C15: one-steering-input on 6/11 laps. One committed steering input entry to apex; 2 correction(s) beyond the jitter floor suggest the entry (speed, line, or vision) wasn't settled. | — | 11 | — | shown | 6 refs |
| vs-principle | C15: throttle-brake-overlap on 7/11 laps. Throttle and brake should not work against each other; 0.83 s of overlap in this corner wastes both. | — | 11 | — | shown | 7 refs |

Suppressed findings: 96 (each with its stated reason — see the JSON report for the full list).

## Cumulative typical loss (s/lap vs robust baseline)

| by phase | s |
|---|---|
| entry | 0.439 |
| exit | 0.796 |
| mid | 1.143 |

| by class | s |
|---|---|
| fast | 0.092 |
| medium | 0.955 |
| slow | 1.332 |

## Corner map

| corner | class | apex (% lap) |
|---|---|---|
| C01 | slow | 6.0 |
| C02 | fast | 19.3 |
| C03 | medium | 35.1 |
| C04 | medium | 38.2 |
| C05 | slow | 44.2 |
| C06 | medium | 46.6 |
| C07 | medium | 54.1 |
| C08 | medium | 64.2 |
| C09 | medium | 71.1 |
| C10 | medium | 73.8 |
| C11 | fast | 75.2 |
| C12 | fast | 79.0 |
| C13 | fast | 84.0 |
| C14 | medium | 87.9 |
| C15 | slow | 96.6 |
| C16 | fast | 89.5 |
| C17 | medium | 56.2 |
| C18 | medium | 72.6 |

## Data quality

Flag counts: {'clipped_pedal': 11} · laps with flags: 11/11

## Not measured (never inferred)

- tire slip/utilization — no slip channel in the source; never inferred
- vision/eye-line — not measurable from telemetry; never inferred
- fuel load, weather, lap validity, stint index — absent from the source contract; controls degrade with stated caveats instead

## Caveats

- lap validity has no source channel: statistical outlier screening with counts, never silent exclusion
