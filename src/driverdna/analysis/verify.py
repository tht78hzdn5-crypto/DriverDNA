"""Mechanical grounding for a lap reading (`driverdna verify-observations`).

The lap-analysis protocol puts a cheap agent to work reading raw traces.
That only pays off if a claim which *sounds* plausible but is not in the data
gets caught by a machine — catching it by careful human reading is the
expensive thing the arrangement exists to avoid.

So this applies the bargain the coach and chat layers already make: prose is
free, numbers are not.

1. Every quoted sample must equal the digest cell at the row it cites.
2. Every numeral in the claim must be one of that observation's own quoted
   samples.

Rule 2 is stricter than `coach.grounding`, which only checks numbers carrying
units, on the reasoning that "units are what turn a number into a measurement
claim". That reasoning does not hold here: the channels a rater talks about
are mostly unitless fractions ("brake reaches 0.62"), so a units-only rule
would check almost nothing. The structured record makes the stricter rule
safe — lap and corner identity live in their own fields, so a numeral in the
prose is always a measurement claim and never a label.

The numeric tolerance itself is `coach.grounding`'s, imported rather than
re-derived, so "does this number match the data" means one thing in this
repository instead of two. It admits honest rounding (43.5 for 43.489) and
refuses invention.

What this does not do is decide whether an observation is interesting or
right as driving analysis. It checks that the numbers are real. Judgment
stays with the reviewer; the point is that the reviewer never spends
attention on a fabricated number.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from driverdna.coach.grounding import matches_number

#: Bumped when the record shape changes in a way a rater would notice.
OBSERVATION_SCHEMA = "obs-v1"

REQUIRED_FIELDS = ("obs_id", "lap", "corner_id", "class", "claim", "quoted")

CLASSES = (
    "phenomenon",       # something is happening in the trace
    "engine_wrong",     # the engine's own output disagrees with the trace
    "coverage_gap",     # real, and nothing in the engine measures it
    "nothing_notable",  # explicitly nothing — the mandatory null answer
)

CONFIDENCES = ("certain", "likely", "unsure")

#: Any numeral in the prose. Deliberately greedy: see the module docstring on
#: why a units-only rule would check almost nothing here.
_NUMERAL = re.compile(r"-?\d+(?:\.\d+)?")


class ObservationError(RuntimeError):
    """The observations file could not be read at all."""


@dataclass
class ObservationResult:
    obs_id: str
    ok: bool
    problems: list[str] = field(default_factory=list)


@dataclass
class VerificationReport:
    results: list[ObservationResult]
    digest_dir: Path

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    def to_markdown(self) -> str:
        lines = [
            "# Observation grounding report",
            "",
            f"Digest: `{self.digest_dir}` · schema `{OBSERVATION_SCHEMA}`",
            "",
            f"**{self.passed} grounded · {self.failed} rejected** "
            f"of {len(self.results)}.",
            "",
            "A rejected observation is not necessarily a wrong reading — it is "
            "one whose numbers could not be tied to the trace, so it is not "
            "put in front of a reviewer. Grounding is not correctness: a "
            "grounded claim still has to survive judgment.",
            "",
        ]
        if self.failed:
            lines += ["## Rejected", ""]
            for r in self.results:
                if not r.ok:
                    lines.append(f"- **{r.obs_id}** — " + "; ".join(r.problems))
            lines.append("")
        lines += ["## Grounded", ""]
        grounded = [r.obs_id for r in self.results if r.ok]
        lines.append(", ".join(f"`{o}`" for o in grounded) if grounded else "_none_")
        lines.append("")
        return "\n".join(lines)


def _load_digest(digest_dir: Path) -> dict[tuple[str, str], dict[int, dict[str, str]]]:
    """(lap dir, corner id) -> row index -> channel -> cell text."""
    manifest_path = digest_dir / "manifest.json"
    if not manifest_path.exists():
        raise ObservationError(f"no digest manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text())

    table: dict[tuple[str, str], dict[int, dict[str, str]]] = {}
    for cohort in manifest["cohorts"]:
        for lap in cohort["laps"]:
            for rel in lap["files"]:
                path = digest_dir / rel
                lines = path.read_text().splitlines()
                header = lines[0].split(",")
                rows: dict[int, dict[str, str]] = {}
                for line in lines[1:]:
                    cells = line.split(",")
                    rows[int(cells[0])] = dict(zip(header[1:], cells[1:], strict=True))
                table[(lap["dir"], Path(rel).stem)] = rows
    return table


def _check(obs: dict, table: dict, seen: set[str]) -> ObservationResult:
    obs_id = str(obs.get("obs_id") or "<no obs_id>")
    problems: list[str] = []

    missing = [f for f in REQUIRED_FIELDS if f not in obs]
    if missing:
        return ObservationResult(obs_id, False, [f"missing field(s): {', '.join(missing)}"])

    if obs_id in seen:
        problems.append(f"duplicate obs_id {obs_id!r}")
    seen.add(obs_id)

    kind = obs["class"]
    if kind not in CLASSES:
        problems.append(f"unknown class {kind!r} (expected one of {', '.join(CLASSES)})")
    if "confidence" in obs and obs["confidence"] not in CONFIDENCES:
        problems.append(f"unknown confidence {obs['confidence']!r}")

    key = (str(obs["lap"]), str(obs["corner_id"]))
    rows = table.get(key)
    if rows is None:
        return ObservationResult(
            obs_id, False,
            problems + [f"no digest slice for lap {obs['lap']!r} corner {obs['corner_id']!r}"],
        )

    quoted = obs["quoted"] or []
    if kind != "nothing_notable" and not quoted:
        problems.append("no quoted sample: a substantive observation must cite the trace")
    if kind == "nothing_notable" and quoted:
        problems.append("a 'nothing_notable' observation should quote nothing")

    supported: list[float] = []
    for q in quoted:
        if not isinstance(q, dict) or not {"row", "channel", "value"} <= set(q):
            problems.append(f"malformed quote {q!r}: needs row, channel, value")
            continue
        row_cells = rows.get(int(q["row"]))
        if row_cells is None:
            problems.append(
                f"row {q['row']} is not in this corner's slice "
                f"(quote a row the digest actually emitted)"
            )
            continue
        if q["channel"] not in row_cells:
            problems.append(f"unknown channel {q['channel']!r}")
            continue
        cell = row_cells[q["channel"]]
        if cell == "":
            problems.append(f"row {q['row']} channel {q['channel']} has no value in the trace")
            continue
        actual = float(cell)
        if not matches_number(float(q["value"]), {actual}):
            problems.append(
                f"quoted {q['channel']}={q['value']} at row {q['row']} "
                f"does not match the trace, which reads {actual}"
            )
            continue
        supported.append(actual)

    for numeral in _NUMERAL.findall(str(obs["claim"])):
        if not matches_number(float(numeral), set(supported)):
            problems.append(
                f"{numeral} appears in the claim but is not one of this "
                f"observation's quoted samples"
            )

    return ObservationResult(obs_id, not problems, problems)


def verify_observations(obs_path: Path, digest_dir: Path) -> VerificationReport:
    """Check every observation in `obs_path` against the digest it cites."""
    table = _load_digest(digest_dir)

    results: list[ObservationResult] = []
    seen: set[str] = set()
    for n, line in enumerate(obs_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obs = json.loads(line)
        except json.JSONDecodeError as exc:
            # Loudly, not skipped: a line that cannot be parsed is an
            # observation nobody will ever review, which is the silent-hole
            # failure this protocol is built to avoid.
            raise ObservationError(f"{obs_path}:{n} is not valid JSON — {exc}") from exc
        if not isinstance(obs, dict):
            raise ObservationError(f"{obs_path}:{n} is not a JSON object")
        results.append(_check(obs, table, seen))

    return VerificationReport(results=results, digest_dir=digest_dir)
