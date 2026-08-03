# Lap-analysis protocol — putting a cheap agent on the traces

**Status: adopted 2026-07-29.** Governs how a high-volume, low-cost agent
(Gemini Flash, via Antigravity or Gemini CLI) is used to read raw telemetry
looking for things the engine misses — and how that reading is checked before
any of it is believed.

Subordinate to `docs/ARCHITECTURE_VISION.md`, `docs/SPEC.md` and `AGENTS.md`.
Nothing here relaxes a non-negotiable. In particular: **the reading agent
never produces a number the engine will use, never edits the engine, and
never decides anything.** It reports what it sees; a reviewer decides.

The tool-neutral name is deliberate. Flash is the first consumer, not the
contract.

---

## Why this exists

Every telemetry tool in the world summarizes laps. This project already does
that better than most, deterministically. What no one has time to do is
*read* the traces — 10,000 samples a lap, twenty channels, twenty-three laps
and counting — looking for the thing no metric was written to catch. That is
real work with real value and it is almost entirely grunt work.

Grunt work at volume is what a cheap model is for. The catch is that a cheap
model is also confidently wrong, and a confidently wrong reading of a trace
is *worse than no reading*, because it looks exactly like a discovery. So the
protocol's whole design is: make the agent's output cheap to check by
machine, and never let an unchecked claim reach a human's attention.

Three mechanisms do that, in order of how much work they save:

1. **Grounding is mechanical.** Every numeral must be quoted from the trace,
   and `driverdna verify-observations` checks each quote against the digest
   bytes. A fabricated number is rejected before anyone reads the sentence.
2. **The read is blind.** The agent sees the trace, not the engine's
   conclusions. So agreement with the engine is evidence, not an echo.
3. **Reliability is measured, not assumed.** Every batch carries laps whose
   ground truth is already known. An agent that misses those has its batch
   discarded unread.

---

## The two artifacts

`driverdna lap-digest` cuts each lap into readable per-corner slices. It
**measures nothing** — row selection and column selection only, asserted
cell-for-cell in `tests/test_lap_digest.py`. That purity is not fastidiousness:
the digest is the shared evidence base for two independent readers, and a bug
in a derived column would corrupt both readings identically, silencing exactly
the disagreement that is supposed to catch it.

`driverdna verify-observations` checks a reading against the digest it claims
to read. It reuses `coach.grounding`'s numeric tolerance rather than defining
a second one.

Neither tool judges whether an observation is *interesting* or *right*. They
establish that the numbers are real. Judgment stays with the reviewer.

---

# Part 1 — Instructions for the reading agent

Paste this section, or point the agent at this file.

## Your job

You are reading raw racing telemetry, one corner at a time, and reporting what
you observe. You are **not** fixing anything, not writing code, and not
deciding anything. Another reviewer decides; your value is volume and fresh
eyes, and it is destroyed entirely by one invented number.

Read `AGENTS.md` at the repository root first. If you cannot read it, stop and
say so rather than proceeding.

## What you read

Only the digest directory you were given (the "blind" directory). Each file is
one lap, one corner:

```
blind/manifest.json          units, channels, corner positions, lap list
blind/<LAP>/<CORNER>.csv     the slice: row index + every stored channel
```

**Read `manifest.json` first.** It tells you the units, and getting them wrong
makes every number you quote wrong. In particular: **speed is m/s, not km/h**
(multiply by 3.6 in your head, never in your output), **steering is degrees**,
yaw rate is rad/s, and brake/throttle are 0–1 fractions.

`row` is the index into the lap's full sample array at 60 Hz. The digest emits
every 6th sample, so consecutive rows are 0.1 s apart. Quote the `row` value
exactly as printed — it is how your claim gets checked.

## What you produce

One JSON object per line (JSONL), to the observations file you were given:

```json
{"obs_id":"B01-9XVJTW-C01-001","lap":"9XVJTW","corner_id":"C01","phase":"entry","class":"phenomenon","claim":"the brake comes back on after an initial release, before the steering settles","quoted":[{"row":4821,"channel":"brake","value":0.62},{"row":4839,"channel":"brake","value":0.31}],"confidence":"likely"}
```

| Field | Meaning |
|---|---|
| `obs_id` | Unique. `<batch>-<lap>-<corner>-<nnn>` works. |
| `lap`, `corner_id` | Exactly as they appear in the digest paths. |
| `phase` | `entry`, `mid`, `exit`, or `none`. |
| `class` | See below. |
| `claim` | One plain sentence about what the trace does. |
| `quoted` | The samples your claim stands on. |
| `confidence` | `certain`, `likely`, or `unsure`. |

**`class` values:**

- `phenomenon` — something is happening in the trace worth a reviewer's time.
- `engine_wrong` — you were shown an engine output and the trace contradicts
  it. Only usable in a non-blind batch; in a blind batch you cannot see engine
  output, so you cannot use this.
- `coverage_gap` — a real, repeatable thing that you believe no metric
  captures. Use sparingly; you do not know the full metric list.
- `nothing_notable` — **explicitly nothing.** Required, see below.

## The rules that get checked by machine

1. **Every numeral in `claim` must appear in `quoted`.** Write "brake reaches
   0.62" only if you quoted a brake sample of 0.62. If you want to say
   something without numbers, say it without numbers — prose is free.
2. **Every `quoted` entry must match the digest at that row.** Copy values
   from the file. Rounding for readability is fine (43.5 for 43.489…);
   inventing is not.
3. **Never put a lap ID or corner ID in `claim`.** They have their own fields,
   and a numeral in the prose is always read as a measurement claim.
4. **A `nothing_notable` observation quotes nothing; every other class must
   quote something.**

Run the checker on your own file before you hand it over:

```
driverdna verify-observations --obs <your file> --digest-dir <blind dir>
```

It exits non-zero if anything is rejected. Fix your own rejects — that is
cheaper for everyone than having them thrown out.

## Say "nothing here" out loud

For every corner you read, emit an observation — even if that observation is
`nothing_notable`. This is not busywork. If you only report the interesting
corners, silence is ambiguous: nobody can tell a clean corner from one you
skipped, and your false-positive rate becomes unmeasurable. A reading with no
null answers in it is not usable.

## Hard prohibitions

- **Never edit** anything under `src/`, `tests/`, `docs/`, or `ui/`. Your only
  output is your observations file.
- **Never touch `tests/fixtures/`.** Those are real recorded laps and the
  regression anchor for the whole project.
- **Never run a `driverdna` command that writes** — `import`, `sync`, `model`,
  `rebuild-map`, `store-copy`, `migrate-blobs`. You need none of them.
- **Never run a report command without `--out`.** `metrics`, `attribution`,
  `incidents`, `coaching`, `model` all default to writing `docs/*-report.md`,
  which are committed byte-identity artifacts. You would silently destroy a
  regression anchor.
- **Never commit, push, or open a pull request.**
- **Never propose a value for a threshold.** Saying "this threshold looks
  wrong for this corner" is useful. Picking its new number is a ConfigStore
  and SPEC-amendment decision, not yours.
- **Never guess when the data is thin.** "Insufficient data" over guessing is
  a project non-negotiable and it applies to you exactly as it applies to the
  engine. An `unsure` observation is worth more than a confident invention.

## What is actually worth reporting

Useful: a pedal or steering movement that repeats across laps at the same
corner; a correction the driver makes; something that happens at one corner
and never at the others; a sample sequence that looks physically odd
(discontinuity, impossible rate of change); anything you would point at if a
driver were sitting next to you.

Not useful: restating that a corner has braking, turning, and acceleration;
one-off noise with no repetition; anything you cannot tie to specific rows.

---

# Part 2 — Runbook for the owner

PowerShell-ready. Substitute your repository path for `C:\DriverDNA`.

**The one thing to get right:** pass `--db` explicitly on every command. Most
commands default to `driverdna.db` or `$DRIVERDNA_DATABASE_URL`, and
`driverdna model` *persists* what it computes. A stray default writes to your
real database.

### 1. Build the batch

```powershell
cd C:\DriverDNA
$B = "C:\DriverDNA\scratch\b01"
New-Item -ItemType Directory -Force -Path $B

driverdna import C:\DriverDNA\tests\fixtures\spa-blind-2026-07 --db $B\laps.db
driverdna lap-digest --db $B\laps.db --out-dir $B\blind
```

### 2. Build the sealed half — engine output nobody reads yet

```powershell
New-Item -ItemType Directory -Force -Path $B\sealed
driverdna metrics      --db $B\laps.db --out $B\sealed\metrics-report.md
driverdna attribution  --db $B\laps.db --out $B\sealed\attribution-report.md
driverdna incidents    --db $B\laps.db --out $B\sealed\incidents-report.md
driverdna coaching     --db $B\laps.db --out $B\sealed\coaching-report.md
driverdna model        --db $B\laps.db --out $B\sealed\driver-model-report.md
driverdna report       --db $B\laps.db --out-dir $B\sealed
```

Every one of those carries an explicit `--out`. Without it they overwrite the
committed artifacts in `docs\`.

### 3. Run the reading agent

Point it at `$B\blind` and this file, and give it an output path under
`docs\lap-analysis\<batch>\`. For Gemini CLI:

```powershell
gemini -m gemini-2.5-flash "Read C:\DriverDNA\docs\LAP-ANALYSIS-PROTOCOL.md Part 1 and follow it. Blind digest: C:\DriverDNA\scratch\b01\blind. Write observations to C:\DriverDNA\docs\lap-analysis\b01\flash-observations.jsonl"
```

For Antigravity, paste Part 1 as the task with the same two paths. Work on an
`antigravity/<topic>` or `gemini/<topic>` branch per `AGENTS.md`.

### 4. Check it before believing it

```powershell
driverdna verify-observations --obs C:\DriverDNA\docs\lap-analysis\b01\flash-observations.jsonl --digest-dir $B\blind --out C:\DriverDNA\docs\lap-analysis\b01\grounding-flash.md
```

Then hand the observations file to the reviewing agent. **Not before** its own
sealed observations are committed — see Part 3.

---

# Part 3 — Verification

## Seal order

The reviewing agent (Claude) reads the same blind digest and writes its own
observations **first**, and commits them, before the reading agent's file
enters the tree. Git history is the proof of order — without it, a reviewer
grading a batch it has already seen is just rationalizing.

1. Owner builds `blind/` and `sealed/`.
2. Reviewer reads `blind/` only → `claude-observations.jsonl` → **commit and
   push**.
3. Reading agent runs → `flash-observations.jsonl`.
4. Only now does the reviewer open `sealed/` and the other file.
5. Reviewer runs `verify-observations` on both, then writes `comparison.md`.

Committed under `docs/lap-analysis/<batch>/`. The `blind/` and `sealed/`
directories are **not** committed — they regenerate byte-identically from the
committed fixtures with the commands in Part 2, so committing them would be
16 MB of derived data.

## Canaries

Reliability is measured per batch, not assumed once.

- **Positive canaries** — laps with known ground truth, unmarked in the batch.
  In `spa-blind-2026-07/` these are `9XVJTW` (a spin) and `9PH9M2` (a full
  stop). Miss both → **the batch is discarded unread**. Miss one → every
  observation in it drops a confidence tier.
- **Negative canary** — a clean, uneventful lap. Inventing a major event there
  counts against precision just as a miss counts against recall.
- **Answer key** — the engine's already-known weak spots, written down
  *before* the batch is read. If the agent only rediscovers those, the batch is
  calibration, not value. Pre-registering them is what stops a reviewer from
  retro-fitting "we knew that" or "that's new" after the fact.

**Pick canaries the reviewer does not already know about.** B01 learned this
the hard way: its reviewer knew which two laps carried incidents before it read
anything, so those observations had to be excluded from the agreement count.
The corpus in fact contained two further incident laps nobody had flagged
(`98D9NK`, `FS2F1N`), and one of them produced the batch's only genuinely
blind hit. Draw canaries from `driverdna incidents` output that the reviewer
has not seen, and keep the mapping out of the reviewer's reach until the seal
is committed.

## Reading the comparison

| | Engine says something | Engine silent |
|---|---|---|
| **Both readers agree** | corroboration — check which is right | **coverage-gap candidate** |
| **Reading agent only** | verify hard, probably noise | probably noise |
| **Reviewer only** | reviewer noise, or an agent miss | reviewer noise, or an agent miss |

The bottom-right of the first column and the top-right cell are where the
value is. Everything else is mostly calibration.

**One trap, and it is easy to fall into.** On a thin corpus the engine is
*supposed* to be quiet: `gates.min_phase_samples` is 10, `gates.min_sessions`
is 2, and the vs-self ranker needs at least 3 laps. A cohort of five laps
suppresses nearly every finding as "insufficient data". A prolific agent next
to a quiet engine then looks like a discovery machine and is nothing of the
kind. On any batch that thin, "engine silent" must be scored **ungated** —
not as a coverage gap.

## Triage

Every grounded observation lands in exactly one bucket:

- `CONFIRMED-GAP` — real, and no metric captures it. → SPEC amendment plus a
  TDD build, later and separately.
- `CONFIRMED-BUG` — the engine measured something wrong. → failing test first,
  then the fix.
- `REJECTED-UNGROUNDED` — numbers did not match the trace. Already filtered
  by the checker; counted for the reliability record.
- `REJECTED-KNOWN` — already a flagged limitation.
- `INSUFFICIENT-DATA` — plausible, N too low to act on. Re-testable when the
  corpus grows.

A reading round changes no engine behaviour by itself. Anything that survives
triage becomes its own piece of work, under the normal rules.

## Recording the result

Per `AGENTS.md` decision discipline: a dated entry in
`docs/PROJECT-BRIEF.md`'s decision log and a `docs/STATUS.md` snapshot update.
A `docs/SPEC.md` amendment only when a finding actually changes engine
behaviour — the reading itself is not an amendment.

---

## Known limits of this protocol

Written down rather than discovered later:

- **Grounding is not correctness.** The checker proves a number was copied
  from the trace, not that the sentence around it is a sound reading. Same
  honest caveat `coach/grounding.py` carries: mechanical enforcement of
  natural language is approximate.
- **The blind is partial.** Slicing by corner means the reader sees where the
  corners are — frozen-map geometry — but not what the engine concluded about
  them. Full blinding would leave observations unmappable and the comparison
  impossible. This is a deliberate trade, not an oversight.
- **A slice can hide the thing.** The window is the corner ±1% of the lap. A
  phenomenon that starts well before that (braking far earlier than usual) is
  partly outside the slice. Widen `--margin` if a batch is aimed at entries.
- **Two readers are not independent enough to be a statistic.** Agreement
  between two language models is weaker evidence than agreement between two
  people; both can share a plausible-sounding wrong prior. Treat the agreement
  cell as a candidate list, never as a result.
