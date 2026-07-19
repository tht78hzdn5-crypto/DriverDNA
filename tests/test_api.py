"""U0 contract tests: pass-through fidelity and write-path equivalence."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.config import load_config
from driverdna.db import Database
from driverdna.ui.api import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SPA_SLUG = "gr86-spa-francorchamps"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    db_path = root / "api.db"
    result = CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    out_dir = root / "reports"
    result = CliRunner().invoke(
        cli_app, ["report", "--db", str(db_path), "--out-dir", str(out_dir)]
    )
    assert result.exit_code == 0, result.output
    client = TestClient(create_app(db_path, root / "config.toml"))
    return {"client": client, "db_path": db_path, "out_dir": out_dir,
            "config_path": root / "config.toml"}


def test_cohort_payload_byte_identical_to_report_json(env):
    api_bytes = env["client"].get(f"/api/cohorts/{SPA_SLUG}/payload").text
    file_bytes = (env["out_dir"] / f"{SPA_SLUG}.json").read_text()
    assert api_bytes == file_bytes


def test_driver_payload_byte_identical_to_report_json(env):
    assert env["client"].get("/api/driver").text == (
        env["out_dir"] / "driver.json"
    ).read_text()


def test_cohorts_and_corners(env):
    cohorts = env["client"].get("/api/cohorts").json()
    assert {c["slug"] for c in cohorts} == {SPA_SLUG, "mustang-laguna-seca"}
    corners = env["client"].get(f"/api/cohorts/{SPA_SLUG}/corners").json()
    # 14 frozen from the first lap + corners admitted from later laps'
    # consistently-unmatched observations (surfaced, never silent).
    assert len(corners) >= 14
    assert corners[0]["corner_id"] == "C01" and corners[0]["class"] == "slow"
    assert all("lat" in c and "windows" in c for c in corners)


def test_track_trace_downsampled(env):
    trace = env["client"].get(f"/api/cohorts/{SPA_SLUG}/track-trace").json()
    assert len(trace["lat"]) == len(trace["lon"]) == len(trace["lap_dist"])
    assert 400 <= len(trace["lat"]) <= 1200
    assert 50.3 < trace["lat"][0] < 50.6  # it's really Spa


def test_laps_listing(env):
    laps = env["client"].get(f"/api/laps?cohort={SPA_SLUG}").json()
    assert len(laps) == 11
    assert {lap["session_key"] for lap in laps} == {
        "gr86-spa-race-1", "gr86-spa-session-2", "gr86-spa-session-3"
    }
    assert all(lap["raw_retained"] for lap in laps)
    assert any(f["code"] == "clipped_pedal" for f in laps[0]["quality_flags"])


def test_metric_distribution_mirrors_db(env):
    r = env["client"].get(
        f"/api/metrics/C01/min_speed_kmh/distribution?cohort={SPA_SLUG}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["n"] == len(body["values"]) >= 8
    with Database.open(env["db_path"]) as db:
        assert body["values"] == db.self_metric_history(
            driver="owner", car="GR86", track="Spa-Francorchamps",
            corner_id="C01", metric="min_speed_kmh",
        )


def test_unmeasured_metric_is_404_not_fabrication(env):
    r = env["client"].get(
        f"/api/metrics/C01/tire_slip/distribution?cohort={SPA_SLUG}"
    )
    assert r.status_code == 404
    assert "not measured" in r.json()["detail"]


def test_annotate_effect_identical_to_db_path(env):
    payload = env["client"].get(f"/api/cohorts/{SPA_SLUG}/payload").json()
    finding_id = payload["findings"][0]["finding_id"]
    r = env["client"].post(
        f"/api/findings/{finding_id}/annotate",
        json={"status": "acknowledged", "note": "known"},
    )
    assert r.status_code == 200 and r.json()["annotated"] == finding_id
    with Database.open(env["db_path"]) as db:
        assert db.annotations()[finding_id]["status"] == "acknowledged"
    after = env["client"].get(f"/api/cohorts/{SPA_SLUG}/payload").json()
    annotated = next(f for f in after["findings"] if f["finding_id"] == finding_id)
    assert annotated["annotation"]["status"] == "acknowledged"

    r = env["client"].post(
        "/api/findings/vs-self:Nope:Nowhere:C99:mid:opportunity/annotate",
        json={"status": "acknowledged"},
    )
    assert r.status_code == 404


def test_clear_annotation_is_reversible(env):
    payload = env["client"].get(f"/api/cohorts/{SPA_SLUG}/payload").json()
    # Use a different finding than the annotate test to avoid shared-state order
    # dependence in this module-scoped env.
    finding_id = payload["findings"][3]["finding_id"]
    env["client"].post(
        f"/api/findings/{finding_id}/annotate", json={"status": "intentional"}
    )
    with Database.open(env["db_path"]) as db:
        assert finding_id in db.annotations()
    r = env["client"].request("DELETE", f"/api/findings/{finding_id}/annotate")
    assert r.status_code == 200 and r.json()["cleared"] == finding_id
    with Database.open(env["db_path"]) as db:
        assert finding_id not in db.annotations()
    # Clearing a finding that isn't annotated is a 404, not a silent no-op.
    r = env["client"].request("DELETE", f"/api/findings/{finding_id}/annotate")
    assert r.status_code == 404


def test_config_propose_stages_nothing_apply_writes(env):
    r = env["client"].post(
        "/api/config/propose",
        json={"key": "detectors.max_corrections", "new_value": 3},
    )
    assert r.status_code == 200
    proposal = r.json()
    assert proposal["old_value"] == 1 and not env["config_path"].exists()

    r = env["client"].post("/api/config/apply", json={"proposal": proposal})
    assert r.status_code == 200
    change = r.json()
    assert change["source"] == "ui" and change["new_value"] == "3"
    assert load_config(env["config_path"]).detectors.max_corrections == 3
    history = env["client"].get("/api/config/history").json()
    assert any(h["change_pk"] == change["change_pk"] for h in history)


def test_config_apply_then_revert_from_ui(env):
    # A distinct key so this doesn't collide with the propose/apply test.
    original = load_config(env["config_path"]).gates.min_sessions
    proposal = env["client"].post(
        "/api/config/propose", json={"key": "gates.min_sessions", "new_value": original + 2}
    ).json()
    change = env["client"].post("/api/config/apply", json={"proposal": proposal}).json()
    assert load_config(env["config_path"]).gates.min_sessions == original + 2

    r = env["client"].post(f"/api/config/revert/{change['change_pk']}")
    assert r.status_code == 200
    assert load_config(env["config_path"]).gates.min_sessions == original
    # The revert is itself an audited change, not an erasure.
    history = env["client"].get("/api/config/history").json()
    assert sum(1 for h in history if h["key"] == "gates.min_sessions") == 2

    assert env["client"].post("/api/config/revert/99999").status_code == 404

    r = env["client"].post(
        "/api/config/propose", json={"key": "detectors.nope", "new_value": 1}
    )
    assert r.status_code == 422
