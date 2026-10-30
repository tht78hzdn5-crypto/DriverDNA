"""Plain-English summary section on the cohort report (owner request,
2026-10-27): the report opened straight into Findings tables. The summary
is presentation only — every sentence renders a value already in the
payload, no new measurement, no LLM call, no invented number."""

from driverdna.report.builder import render_cohort_html, render_cohort_markdown


def _finding(*, corner="C06", phase="mid", gap_median=1.027, gap_best=0.067,
             shown=True):
    return {
        "finding_id": f"vs-reference:TestCar:SynthRing:{corner}:{phase}:gap",
        "source": "vs-reference",
        "car": "TestCar",
        "track": "SynthRing",
        "corner_id": corner,
        "phase": phase,
        "kind": "gap",
        "description": f"{corner} mid-corner: gap to reference "
                       f"{gap_median:+.3f} s typical, {gap_best:+.3f} s best",
        "seconds": gap_median,
        "n": 18,
        "spread": 0.1,
        "evidence_ids": ["obs:1"],
        "shown": shown,
        "gate_reason": None,
        "fundamental": "rotation",
        "details": {"gap_median_s": gap_median, "gap_best_s": gap_best,
                    "reference_n": 4},
        "annotation": None,
    }


def _payload(*, durations=(90.463, 91.091, 92.0), incomplete=(False, False, False),
             by_phase=None, by_class=None, findings=(), headline=None):
    if by_phase is None:
        by_phase = {"entry": 0.329, "mid": 2.443, "exit": 2.475}
    if by_class is None:
        by_class = {"medium": 0.165, "slow": 5.082}
    coaching = None
    if headline is not None:
        coaching = {"headline": {"coaching_expression": headline,
                                 "driving_principle": "Why.",
                                 "drill": "Drill.",
                                 "fundamental": "consistency"},
                    "secondary": []}
    return {
        "payload_version": 13,
        "cohort": {"driver": "owner", "car": "TestCar", "track": "SynthRing",
                   "n_laps": len(durations), "n_sessions": 2,
                   "lap_durations_s": list(durations),
                   "lap_ids": [None] * len(durations),
                   "lap_incomplete": list(incomplete),
                   "lap_delta_s": [None] * len(durations)},
        "quality": {"flag_counts": {}, "n_laps_flagged": 0},
        "corner_map": [],
        "metrics": {},
        "metric_definitions": {},
        "phase_baselines": {},
        "cumulative_loss": {"per_corner": {}, "by_phase": by_phase,
                            "by_class": by_class, "outliers_screened": {}},
        "findings": list(findings),
        "unavailable_fundamentals": [],
        "driver_model": None,
        "coaching": coaching,
        "incidents": {"events": []},
        "references": {"envelope": None, "n": 0, "contributors": 0,
                       "n_excluded": 0},
        "caveats": [],
    }


def test_markdown_summary_sits_before_findings_and_states_the_facts():
    md = render_cohort_markdown(_payload(
        findings=[_finding()], headline="Match a lap before you try to beat it."))
    assert md.index("## Summary") < md.index("## Findings")
    assert "3 laps across 2 sessions at TestCar @ SynthRing" in md
    assert "Best lap 1:30.463" in md
    assert "exit phase (2.475 s/lap)" in md
    assert "Slow corners carry the largest share (5.082 s/lap)" in md
    assert "C06 mid-corner (+1.027 s)" in md
    assert "Match a lap before you try to beat it." in md


def test_markdown_summary_says_plainly_when_no_reference_comparison():
    md = render_cohort_markdown(_payload(findings=[]))
    assert "no reference comparison" in md


def test_markdown_summary_handles_empty_loss_and_no_headline():
    md = render_cohort_markdown(_payload(by_phase={}, by_class={}))
    assert "## Summary" in md
    assert "phase (" not in md
    assert "carry the largest share" not in md


def test_markdown_summary_excludes_incomplete_laps_from_best():
    md = render_cohort_markdown(_payload(
        durations=(80.0, 90.463), incomplete=(True, False)))
    assert "Best lap 1:30.463" in md


def test_html_summary_mirrors_markdown_and_comes_first():
    html = render_cohort_html(_payload(
        findings=[_finding()], headline="Match a lap before you try to beat it."))
    assert html.index("<h2>Summary</h2>") < html.index("<h2>Findings</h2>")
    assert "3 laps across 2 sessions" in html
    assert "Best lap 1:30.463" in html
    assert "C06 mid-corner (+1.027 s)" in html
    assert "Match a lap before you try to beat it." in html
