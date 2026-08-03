# Batch B01 — reviewer's read disclosure

Written and committed at the same time as `claude-observations.jsonl`, before
the reading agent's file existed and before any `sealed/` engine output was
opened. What a reader actually looked at is part of the evidence; without it,
"I found three things" is not comparable to anyone else's three things.

## What I read

- **`QHD9QC/C01` in full** — every emitted row, every channel. The negative
  canary and the fastest lap in the corpus, read first to establish what
  ordinary looks like.
- **`GZHYTY/C01`, partially** — the exit portion, to check a gear/RPM question
  raised by the first lap.
- **`*/C01` across all eleven laps** — scanned, not read line by line, for two
  specific patterns (gear index versus speed; brake re-application after
  release).
- **`*/C0*`–`*/C18` across all eleven laps** — scanned for the brake
  re-application pattern only. One dimension, not a read.
- Exact cells for every value I quote, pulled individually.

## What I did not read

Everything else. That is 198 slices in the batch and I read one of them
completely. **`C02` through `C18` were never read in the sense a reading agent
is asked to read them** — I pattern-scanned them for a single phenomenon I had
already found elsewhere.

Consequently my `nothing_notable` entries for `QHD9QC` corners C02, C04, C06,
C10–C14, C16 and C18 mean only *"no brake re-application here"*. They are not
the considered "I looked and there is nothing" that the protocol asks for, and
they should not be counted as such. I emitted them so the shape of my file is
comparable; the honest reading of them is in this paragraph.

This is the reviewer's own coverage being thin, not a flaw in the batch. If
the reading agent reads all 198 slices properly, its coverage is genuinely
better than mine, and any corner it reports on outside C01/C05/C08/C09/C15 is
territory I cannot corroborate either way.

## Blinding

I did not open `scratch/b01/sealed/` — it had not been generated at the time
of writing — and consulted no engine metric, finding, baseline, incident,
coaching or attribution output for this corpus.

The one contamination is disclosed in `answer-key.md`: I knew before reading
that `9XVJTW` contains a spin and `9PH9M2` a near-stop, and roughly where.
Neither appears in my observations; both are excluded from any agreement
count.

## Method note

I read via column projection (viewing a subset of channels at a time) and used
shell scans to test whether a pattern repeated across laps. A reading agent
working slice-by-slice in a chat window has a different, narrower instrument.
That asymmetry is worth remembering when comparing the two: where I found
something by scanning eleven laps at once, an agent reading one slice at a
time is not being tested on the same task.
