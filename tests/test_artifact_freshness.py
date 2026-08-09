"""BUG-020: every committed artifact must match what the code regenerates.

The inspectable artifacts (`docs/*-report.md` and the root cohort/driver
reports) are committed as regression anchors and read as current — by humans
and by agents. Nothing enforced that. A42 (`coach-onto-v2`) and A43 (census)
each changed numbers those files contain without regenerating them, and three
sat stale for days across two merges; the A46 session then had to regenerate
on a clean checkout to prove the drift was pre-existing rather than its own
regression.

This is the guard. It regenerates every artifact from `tests/fixtures/` into a
temp directory and byte-compares. Byte, not fuzzy: the repo already claims
byte-identical determinism everywhere (AGENTS.md's determinism rule,
`test_report.py`'s independent-render test), so anything looser would be a
weaker promise than the one already made.

Verified before adopting, rather than assumed safe: all fourteen artifacts
regenerate byte-identical under **both** CI matrix versions, Python 3.11 and
3.12, and across two different numpy majors (system numpy and 2.5.2). If this
ever fails for a platform reason rather than a real change — a numpy release
altering a last decimal, or the ARM64 divergence in BUG-019 — that is itself
a finding worth having, not noise to silence. Investigate before loosening
it; never weaken this test to make a push green (AGENTS.md, Scope).

Cost: one full fixture import shared across the module, the same work
`test_render_parity.py` and `test_coaching_report.py` already each do once.
"""

from __future__ import annotations

from contextlib import chdir
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driverdna.cli import app

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "tests" / "fixtures"

# (CLI command, committed filename under docs/). Each takes --db/--out.
_DB_REPORTS = (
    ("metrics", "metrics-report.md"),
    ("attribution", "attribution-report.md"),
    ("coaching", "coaching-report.md"),
    ("incidents", "incidents-report.md"),
    ("model", "driver-model-report.md"),
    ("census", "census-report.md"),
)

# These read the fixture CSVs directly and never open a database. They are
# regenerated below from the repo root with the *relative* default path,
# because `corners` prints the fixtures directory it was given into its own
# header — so its output is cwd-dependent, and only the documented
# invocation (`driverdna corners`, run from the repo root) reproduces the
# committed file. Caught by this test on its first run; left as-is rather
# than fixed, since relativising that header would itself change a committed
# artifact and belongs in its own change.
_FIXTURE_DIR_ARG = "tests/fixtures"
_FIXTURE_REPORTS = (
    ("corners", "corners-report.md"),
    ("schema-report", "schema-report.md"),
)

# `driverdna report` writes one set per cohort; only these are committed at
# the repo root. It also emits `mustang-laguna-seca.*` from the single-lap
# Mustang cohort, which is deliberately not committed — so it is regenerated
# here and simply not compared.
_ROOT_REPORTS = (
    "gr86-spa-francorchamps.md",
    "gr86-spa-francorchamps.json",
    "gr86-spa-francorchamps.html",
    "driver.md",
    "driver.json",
    "driver.html",
)

# How to bring each artifact back into sync, quoted verbatim in the failure.
_REGEN = {
    **{name: f"driverdna {cmd} --db <db> --out docs/{name}" for cmd, name in _DB_REPORTS},
    **{name: f"driverdna {cmd} --out docs/{name}" for cmd, name in _FIXTURE_REPORTS},
    **{name: "driverdna report --db <db> --out-dir ." for name in _ROOT_REPORTS},
}


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory) -> Path:
    """Every artifact, rebuilt from the fixtures into one temp directory."""
    root = tmp_path_factory.mktemp("artifact-freshness")
    db = root / "fixtures.db"
    out = root / "out"
    out.mkdir()
    runner = CliRunner()

    def run(*args: str) -> None:
        result = runner.invoke(app, list(args))
        assert result.exit_code == 0, f"`{' '.join(args)}` failed:\n{result.output}"

    # From the repo root, so the relative fixtures path below resolves and
    # matches how the committed artifacts were generated.
    with chdir(REPO):
        run("import", str(FIXTURES), "--db", str(db))
        for command, name in _DB_REPORTS:
            run(command, "--db", str(db), "--out", str(out / name))
        for command, name in _FIXTURE_REPORTS:
            run(command, "--fixtures-dir", _FIXTURE_DIR_ARG, "--out", str(out / name))
        run("report", "--db", str(db), "--out-dir", str(out))
    return out


def _display(path: Path) -> str:
    """Repo-relative where possible — the failure message is read by someone
    about to run a command, so it should name the file the way they will."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _assert_fresh(committed: Path, fresh: Path, name: str) -> None:
    assert committed.exists(), (
        f"{_display(committed)} is committed as an inspectable "
        f"artifact but is missing. Regenerate: {_REGEN[name]}"
    )
    assert fresh.exists(), f"regeneration produced no {name} — the generator changed?"
    if committed.read_bytes() == fresh.read_bytes():
        return
    # Lead with the first differing line: "they differ" alone sends the reader
    # diffing 7,000 lines of JSON by hand.
    old = committed.read_text().splitlines()
    new = fresh.read_text().splitlines()
    detail = "lengths differ only"
    for i, (a, b) in enumerate(zip(old, new, strict=False), start=1):
        if a != b:
            detail = f"first difference at line {i}:\n  committed: {a[:200]}\n  fresh:     {b[:200]}"
            break
    raise AssertionError(
        f"{_display(committed)} is stale — it does not match what the "
        f"code regenerates from tests/fixtures/ ({len(old)} lines committed, "
        f"{len(new)} fresh).\n{detail}\n\n"
        f"If a number moved deliberately, regenerate and commit the artifact "
        f"in the same change: {_REGEN[name]}\n"
        f"If no number should have moved, this is a real regression — find it "
        f"before regenerating (BUG-020, docs/BUG-LOG.md)."
    )


@pytest.mark.parametrize("name", [n for _, n in _DB_REPORTS + _FIXTURE_REPORTS])
def test_committed_docs_report_is_current(regenerated, name):
    _assert_fresh(REPO / "docs" / name, regenerated / name, name)


@pytest.mark.parametrize("name", _ROOT_REPORTS)
def test_committed_root_report_is_current(regenerated, name):
    _assert_fresh(REPO / name, regenerated / name, name)


def test_the_guard_covers_every_committed_docs_report():
    """A new `docs/*-report.md` must be added to this file's tables, or it
    would be committed and then drift with nothing watching it — which is the
    entire bug this guard exists for."""
    on_disk = {p.name for p in (REPO / "docs").glob("*-report.md")}
    covered = {name for _, name in _DB_REPORTS + _FIXTURE_REPORTS}
    unwatched = on_disk - covered
    assert not unwatched, (
        f"committed report(s) no freshness test covers: {sorted(unwatched)} — "
        "add each to _DB_REPORTS or _FIXTURE_REPORTS with its regeneration "
        "command"
    )


def test_the_guard_would_catch_a_stale_artifact(tmp_path):
    """Guard the guard (the `test_crawler_would_catch_an_invented_number`
    precedent): a freshness check that cannot detect staleness is worse than
    none, because it reads as coverage. Mutate one digit of a real committed
    artifact and assert the comparison rejects it."""
    real = REPO / "docs" / "metrics-report.md"
    original = real.read_text()

    drifted = tmp_path / "metrics-report.md"
    # Change exactly one character of one number, the smallest realistic drift.
    for i, ch in enumerate(original):
        if ch.isdigit():
            drifted.write_text(original[:i] + ("9" if ch != "9" else "8") + original[i + 1:])
            break
    else:  # pragma: no cover - the report always contains numbers
        pytest.fail("no digit found in metrics-report.md to mutate")

    assert drifted.read_text() != original, "sanity: the mutation must change the file"
    with pytest.raises(AssertionError, match="is stale"):
        _assert_fresh(drifted, real, "metrics-report.md")
