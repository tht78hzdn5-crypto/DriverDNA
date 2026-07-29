# GEMINI.md — redirect

The build rules for this repository are in **`AGENTS.md`** at the repository
root. This file holds none of them, deliberately — one copy, no drift.

`.gemini/settings.json` sets `context.fileName` so `AGENTS.md` loads
automatically. This stub exists in case that setting is ever not honoured,
since Gemini CLI's default is to load `GEMINI.md` alone.

**Before your first edit: read `AGENTS.md` in full.** If you cannot read it,
stop and tell the owner rather than proceeding from this file.

Gemini-CLI specifics:

- Work on a `gemini/<topic>` branch. Never commit to `main`.
- Commit trailers: `Agent: gemini-cli` and
  `Co-Authored-By: Gemini CLI <noreply@google.com>`.
- Run `python3 -m pytest` before you change anything and again before you push;
  merge only on green CI.
- If your task is **reading laps to find gaps in the engine**, follow
  `docs/LAP-ANALYSIS-PROTOCOL.md` Part 1 instead of the build workflow: it
  produces observations only — no repository edits, no commits, and every
  number quoted from the trace so `driverdna verify-observations` can check
  it mechanically.
