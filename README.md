# DriverDNA

A personal racing-telemetry instrument. It ingests Garage61 lap exports (iRacing),
segments corners, measures technique deterministically, attributes time lost per
corner phase, and reports transferable findings denominated in cumulative seconds —
sharpening as laps accumulate. An AI coaching layer (one-shot plan + grounded chat)
explains and prioritizes the deterministic findings; it never invents a measurement.

Optimize the driver, not the lap.

## Quickstart — see the cockpit in one command

```bash
git clone <this repo> && cd DriverDNA
python3 -m pip install -e ".[dev]"
driverdna demo
```

`driverdna demo` seeds the bundled sample laps into a throwaway DB under
`~/.driverdna/` and opens the local cockpit — track map, findings, the Driver
Model, incidents, config — in your browser at `http://127.0.0.1:8710`. No data
or API key needed. It's the same UI as `driverdna ui`, just pointed at demo
data so there's something to look at immediately.

Then, to run it on **your** telemetry:

```bash
driverdna sync                 # pull your own Garage61 laps (needs GARAGE61_TOKEN)
# or: driverdna import <dir> --car GR86 --track Spa-Francorchamps --date 2026-07-15
driverdna ui                   # same cockpit, your data
driverdna report               # or a self-contained HTML/Markdown/JSON report, no server
```

The cockpit binds to `127.0.0.1` only and makes no external network requests —
a deliberate privacy property, not an oversight. AI layers (`driverdna coach` /
`chat`) additionally need `ANTHROPIC_API_KEY`; everything else is offline.

- **Authoritative spec:** [`docs/SPEC.md`](docs/SPEC.md) — product intent, philosophy,
  verified source contract, milestones, and acceptance gates.
- **Current status:** [`docs/STATUS.md`](docs/STATUS.md) — the engine (M0a–M7),
  the UI (U0–U4), sync, and the incident subsystem are all built and tested.
- **Build rules for agents:** [`CLAUDE.md`](CLAUDE.md).

Personal instrument, not a product: local CLI, SQLite, static self-contained reports.
No server, no blended scores, no guessing — "insufficient data" is a valid answer.
