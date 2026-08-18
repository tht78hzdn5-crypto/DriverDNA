# BUG-019 — ARM64 Test Failures: Diagnostic Guide

> **⚠️ SUPERSEDED (2026-08-17)** — This guide's premise is false. The Oracle VM
> is **x86_64** with ~960 MB RAM, not ARM64 (Ampere A1). The exact instance
> shape is unverified — see BUG-019. The architecture claim was written as fact on 2026-08-08 (STATUS.md,
> commit 152f291) but never verified. A full diagnostic run on 2026-08-16
> confirmed x86_64 via `uname -m` and found 944 passed / 1 failed (a known
> code-test mismatch, BUG-023, already fixed). The five failure categories
> below, and their x87-vs-IEEE-754 reasoning, do not apply. See BUG-019's
> corrected entry in `docs/BUG-LOG.md` for the actual findings. The leading
> hypothesis for the original 2026-08-08 failures is OOM on the ~960 MB machine.

**For**: Antigravity (or any agent on the Oracle VM)
**Bug**: `pytest` fails on the Ampere A1 (aarch64) VM at roughly 15%, 31%, and
38% of the run. Same commit is green on x86. Tracebacks were never captured
because the first run used bare `pytest` with no output capture, and nobody has
gone back.

**Goal of this session**: capture the failures with enough detail to classify
them, then report back. **Do not fix anything yet** — the first step is reading
the errors, not guessing at them.

---

## Step 0 — Pre-flight

```bash
# Confirm you're on the right machine
uname -m                # expect: aarch64
python3 --version       # expect: 3.11 or 3.12

# Pull latest main (PR #26 just merged)
cd /opt/driverdna/DriverDNA
sudo -u driverdna git pull origin main

# Install in dev mode so pytest + fixtures are available
sudo /opt/driverdna/venv/bin/pip install -e ".[dev]"
```

---

## Step 1 — Capture the full run

This is the single most important command. Everything else is optional.

```bash
sudo -u driverdna /opt/driverdna/venv/bin/python -m pytest \
  --tb=long -v 2>&1 | tee /var/lib/driverdna/pytest-arm64.txt
```

**Why `--tb=long -v`**: short tracebacks hide the actual assertion values.
We need the exact numbers that diverged — `0.12345678` expected vs
`0.12345679` received tells us float precision; `["B", "A"]` expected vs
`["A", "B"]` tells us collation/sort order.

**Why `tee`**: the output goes to both the terminal and a file, so it
survives if the session disconnects.

If the run takes too long or memory is tight (the VM is 12 GB), you can
split it:

```bash
# Run just the files around the known failure positions (15%, 31%, 38%)
sudo -u driverdna /opt/driverdna/venv/bin/python -m pytest \
  tests/test_parser.py tests/test_schema_lock.py tests/test_api.py \
  tests/test_attribution.py tests/test_segmenter.py tests/test_metrics.py \
  tests/test_scoring.py tests/test_artifact_freshness.py \
  --tb=long -v 2>&1 | tee /var/lib/driverdna/pytest-arm64-targeted.txt
```

---

## Step 2 — Capture the environment

These commands take seconds and rule out "wrong numpy" or "wrong Python":

```bash
sudo -u driverdna /opt/driverdna/venv/bin/python -c "
import sys, platform, struct
print('Python:', sys.version)
print('Platform:', platform.platform())
print('Machine:', platform.machine())
print('Byte order:', sys.byteorder)
print('Float info:')
print('  max:', sys.float_info.max)
print('  epsilon:', sys.float_info.epsilon)
print('  dig:', sys.float_info.dig)
print('  mant_dig:', sys.float_info.mant_dig)
print('Pointer size:', struct.calcsize('P') * 8, 'bit')
"

sudo -u driverdna /opt/driverdna/venv/bin/python -c "
import numpy, scipy, sqlite3
print('numpy:', numpy.__version__)
print('scipy:', scipy.__version__)
print('sqlite3:', sqlite3.sqlite_version)
print('numpy float64 eps:', numpy.finfo(numpy.float64).eps)
print('numpy float32 eps:', numpy.finfo(numpy.float32).eps)
"
```

Save both outputs:
```bash
# (redirect the above two blocks into /var/lib/driverdna/env-arm64.txt)
```

---

## Step 3 — What to look for in the output

Classify each failure into one of these categories. The category determines
whether it is a real engine bug or a test-tolerance issue.

### Category A: Float precision divergence

**Pattern**: an `assert x == y` where x and y differ in the last 1–3
decimal digits. Example:
```
assert 0.12345678901234 == 0.12345678901237
```

**Why it happens on ARM64**: x86's legacy FPU carries 80-bit extended
precision intermediates; ARM64 uses strict IEEE 754 double (64-bit)
throughout. A chained multiply-add on x86 keeps extra precision in
registers that ARM64 rounds away. Both are correct IEEE 754 — x86 just
happens to be "more correct" by accident.

**This repo's exposure**: almost every test uses exact `==` on floats
(only 10 assertions across the whole suite use `approx`/`isclose`). The
engine's metrics, phase times, baselines, and scores are all `float64`
chains. The committed artifacts (`docs/*-report.md`, `docs/*-report.json`)
are **byte-exact** golden files — a single digit's drift fails
`test_artifact_freshness.py`'s 16 tests.

**What to report**: the test name, the expected value, the actual value,
and how many digits agree. Example:
```
test_artifact_freshness.py::test_gr86_spa_json — expected "1.234567" got "1.234568"
                                                  agrees to 6 digits
```

### Category B: Sort-order divergence

**Pattern**: a list/dict comparison where the elements are the same but in
a different order. Example:
```
assert corners == [{"id": "C01", ...}, {"id": "C02", ...}]
# got [{"id": "C02", ...}, {"id": "C01", ...}]
```

**Why it happens on ARM64**: SQLite's default collation is the same on
both architectures (binary/memcmp), so this is unlikely from the DB. More
likely: Python `dict` iteration order is insertion order but **hash
randomization** (`PYTHONHASHSEED`) can affect `set()` iteration or
`dict.fromkeys()` order. Also possible: a `sorted()` on floats that are
equal-to-epsilon on x86 but not on ARM64, making the sort unstable across
platforms.

**What to report**: the test name, the two orderings, and whether the
elements are identical (just reordered) or have different values too.

### Category C: Collation / locale divergence

**Pattern**: string comparisons or sorted-string outputs differ.

**Why**: the VM may have a different default locale than the CI runner.
The engine uses `COLLATE "C"` in Postgres but SQLite's default `BINARY`
collation is locale-independent, so this is less likely — but check.

**What to report**: `locale` output from the VM.

### Category D: Genuine logic bug exposed by ARM64

**Pattern**: a completely wrong answer — not a last-digit float drift but
a structurally different result (wrong number of corners detected, wrong
class assigned, wrong finding emitted).

**This is the dangerous one.** BUG-006 (Postgres float4 truncation) was
exactly this shape — a platform difference exposing a real precision
dependency in the engine. The engine's numbers are float-sensitive by
design (hysteresis thresholds, outlier fences, tercile boundaries), so a
rounding difference that crosses a threshold is a real bug, not a
cosmetic one.

**What to report**: the full traceback, the test's docstring (it usually
explains what the test is checking), and the actual vs expected values.

### Category E: Environment / infra failure

**Pattern**: `ImportError`, `FileNotFoundError`, `PermissionError`,
missing fixture, timeout.

**What to report**: the error message. These are setup problems, not
engine bugs.

---

## Step 4 — The triage table

After the run, fill in this table (one row per failing test):

```
| Test | Category | Expected | Got | Digits agree | Notes |
|------|----------|----------|-----|--------------|-------|
| ...  | A/B/C/D/E| ...      | ... | ...          | ...   |
```

---

## Step 5 — Two targeted experiments (if Category A dominates)

If most failures are last-digit float divergence, run these two commands to
measure the scope:

### 5a. Artifact freshness with tolerant diff

```bash
sudo -u driverdna /opt/driverdna/venv/bin/python -m pytest \
  tests/test_artifact_freshness.py -v --tb=long \
  2>&1 | tee /var/lib/driverdna/freshness-arm64.txt
```

Then regenerate the artifacts on the VM and diff:

```bash
cd /opt/driverdna/DriverDNA

sudo -u driverdna /opt/driverdna/venv/bin/driverdna schema-report \
  --fixtures-dir tests/fixtures --out docs/schema-report.md

sudo -u driverdna /opt/driverdna/venv/bin/driverdna corners \
  --out docs/corners-report.md

sudo -u driverdna /opt/driverdna/venv/bin/driverdna metrics \
  --fixtures-dir tests/fixtures --out docs/metrics-report.md

sudo -u driverdna /opt/driverdna/venv/bin/driverdna attribution \
  --fixtures-dir tests/fixtures --out docs/attribution-report.md

# Diff against the committed versions:
git diff --stat
git diff docs/ | head -200
```

This tells us exactly which numbers moved and by how much.

### 5b. Float chain isolation

```bash
sudo -u driverdna /opt/driverdna/venv/bin/python -c "
import numpy as np

# Reproduce the engine's actual computation chain on a known input
a = np.array([1.23456789012345, 2.34567890123456, 3.45678901234567])
print('sum:', repr(a.sum()))
print('mean:', repr(a.mean()))
print('std:', repr(a.std()))
print('median:', repr(np.median(a)))

# A chained multiply-add (the shape of a metric computation)
b = a * 1.1 + 0.5
c = b.cumsum() / np.arange(1, len(b) + 1)
print('chained result:', repr(c))
"
```

Run this on both x86 (CI or local) and ARM64 and diff the `repr()` output.
If they diverge, that is the root cause.

---

## What to report back

Commit or paste the following files:

1. **`pytest-arm64.txt`** — the full `--tb=long -v` output (Step 1)
2. **`env-arm64.txt`** — the environment snapshot (Step 2)
3. **The triage table** (Step 4) — even a partial one is useful
4. **`freshness-arm64.txt`** and `git diff` output (Step 5a, if applicable)

If the output is too large to paste, commit it on a branch:

```bash
cd /opt/driverdna/DriverDNA
sudo -u driverdna git checkout -b antigravity/bug-019-arm64-capture
sudo -u driverdna cp /var/lib/driverdna/pytest-arm64.txt docs/
sudo -u driverdna cp /var/lib/driverdna/env-arm64.txt docs/
sudo -u driverdna git add docs/pytest-arm64.txt docs/env-arm64.txt
sudo -u driverdna git commit -m "$(cat <<'EOF'
docs: BUG-019 ARM64 test failure capture

Raw pytest output and environment snapshot from the Ampere A1 VM.
Diagnostic only — no code changes.

Agent: antigravity
Co-Authored-By: Antigravity <noreply@google.com>
EOF
)"
sudo -u driverdna git push -u origin antigravity/bug-019-arm64-capture
```

---

## What NOT to do

- **Do not fix the tests.** The failures may be real engine bugs (Category
  D). Weakening a test to go green on ARM64 could hide a genuine precision
  dependency.
- **Do not regenerate and commit artifacts.** If the ARM64 numbers differ,
  committing them would make x86 CI fail.
- **Do not skip or `xfail` tests.** AGENTS.md non-negotiable: "Never
  weaken, delete, skip, xfail, or narrow a test to pass."
- **Do not theorize before reading.** The bug entry says this explicitly.
  Capture first, classify second, fix third (in a separate session with
  the data in hand).
