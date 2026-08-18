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

The cockpit binds to `127.0.0.1` only, and the browser app itself makes no
external network request on any route — no CDN, no font host, no telemetry.
That is a deliberate privacy property, not an oversight, and it is enforced by
a test that blocks all non-local traffic and drives every route.

Where your data lives is your choice. By default everything is local: a SQLite
file plus raw telemetry beside it, and the server makes no outbound connection
at all. Point `DRIVERDNA_DATABASE_URL` at a Postgres instance and the
*queryable rows* move there instead — raw lap traces always stay on local
disk. AI layers (`driverdna coach` / `chat`) additionally need
`ANTHROPIC_API_KEY`; nothing else reaches the network.

- **Authoritative spec:** [`docs/SPEC.md`](docs/SPEC.md) — product intent, philosophy,
  verified source contract, milestones, and acceptance gates.
- **Current status:** [`docs/STATUS.md`](docs/STATUS.md) — the engine (M0a–M7),
  the UI (U0–U4), sync, and the incident subsystem are all built and tested.
- **Build rules for agents:** [`CLAUDE.md`](CLAUDE.md).

Personal instrument, not a product: local CLI, static self-contained reports,
one driver's data. No blended scores, no guessing — "insufficient data" is a
valid answer. Storage is SQLite by default and optionally a private,
single-tenant Postgres; see `docs/SPEC.md` amendment A23 for exactly what that
does and does not change.

## License

Copyright (C) 2026 Ben Richards

DriverDNA is free software: you may redistribute it and/or modify it under the
terms of the **GNU Affero General Public License, version 3 or later**, as
published by the Free Software Foundation. It is distributed in the hope that
it will be useful, but WITHOUT ANY WARRANTY — without even the implied warranty
of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the full text in
[`LICENSE`](LICENSE), or <https://www.gnu.org/licenses/>.

AGPL rather than GPL because DriverDNA is network server software: if you run a
modified version as a service, §13 requires you to offer that service's users
the corresponding source. Running an unmodified copy for yourself carries no
such obligation.

