"""U0 contract tests: pass-through fidelity and write-path equivalence."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.config import load_config
from driverdna.db import Database
from driverdna.ui.api import create_app

from conftest import requires_postgres

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


def test_health_endpoint_does_not_open_db():
    # A path that cannot possibly resolve to a real store — if /health opened
    # the DB, this would 404 or raise instead of answering.
    client = TestClient(
        create_app(Path("/nonexistent-dir/does-not-exist.db"), Path("/nonexistent-dir/config.toml"))
    )
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "store": "sqlite", "auth": False}


def test_health_reports_postgres_backend_and_never_the_dsn():
    """SPEC.md A41 / docs/VM-MIGRATION.md §3.7.3: `store` and `auth` are the
    two non-secret deployment facts that would have made the Cloud Run
    sign-in bounce a five-second diagnosis instead of four sessions of
    auth-code changes — confirmable from a browser rather than inferred from
    behaviour. Enum + bool only; the DSN (which carries the password) must
    never appear."""
    client = TestClient(
        create_app(
            "postgresql://user:hunter2@nonexistent-host/db",
            Path("/nonexistent-dir/config.toml"),
        )
    )
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "store": "postgres", "auth": False}
    assert "hunter2" not in resp.text


def test_health_reports_auth_configured_and_never_the_secret():
    client = TestClient(
        create_app(
            Path("/nonexistent-dir/does-not-exist.db"),
            Path("/nonexistent-dir/config.toml"),
            session_secret="a-real-secret",
        )
    )
    resp = client.get("/health")
    assert resp.json() == {"status": "ok", "store": "sqlite", "auth": True}
    assert "a-real-secret" not in resp.text


def test_unhandled_exception_returns_structured_500_not_a_traceback(env, monkeypatch):
    import driverdna.ui.api as api_module

    def boom(*args, **kwargs):
        raise RuntimeError("simulated unhandled failure")

    monkeypatch.setattr(api_module, "build_driver_payload", boom)
    # raise_server_exceptions=False: the default TestClient re-raises server
    # errors for the test to catch directly, which is the opposite of what
    # this test checks — that a live deployment gets a structured response,
    # not a bare crash.
    no_raise_client = TestClient(
        create_app(env["db_path"], env["config_path"]), raise_server_exceptions=False
    )
    resp = no_raise_client.get("/api/driver")
    assert resp.status_code == 500
    body = resp.json()
    assert body.get("detail") == "internal server error"


@requires_postgres
def test_postgres_backed_app_serves_requests_through_a_connection_pool(pg_schema, tmp_path):
    from psycopg_pool import ConnectionPool

    result = CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", pg_schema]
    )
    assert result.exit_code == 0, result.output
    app = create_app(pg_schema, tmp_path / "config.toml")
    with TestClient(app) as client:
        # A real pool, not the single-shared-connection scheme it replaces:
        # that distinction matters because FastAPI dispatches sync routes to
        # a thread pool, and one psycopg connection shared across
        # concurrently-executing requests is not safe.
        assert isinstance(app.state.pool, ConnectionPool)
        r1 = client.get("/api/driver")
        r2 = client.get("/api/cohorts")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert {c["slug"] for c in r2.json()} == {SPA_SLUG, "mustang-laguna-seca"}


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


# --- Reference laps R2/R3 (SPEC.md A39): identity + curation endpoints ------
#
# A dedicated fixture, not the shared module-scoped `env` above: curation
# writes (exclude/include) mutate DB state, and building this needs a real
# reference lap the shared fixture deliberately never carries (its
# byte-identical report/render-parity anchors would be perturbed by one).


@pytest.fixture()
def ref_env(tmp_path):
    """One self cohort (GR86 @ Spa-Francorchamps, from the shared fixtures)
    plus one reference lap from the spa-blind-2026-07/ subdirectory, which
    `driverdna import FIXTURES_DIR` never touches (non-recursive glob) —
    so its content_hash was never claimed by the self import, and it can
    import cleanly as a second, reference-role lap into the same cohort."""
    result = CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(tmp_path / "ref.db")]
    )
    assert result.exit_code == 0, result.output
    db_path = tmp_path / "ref.db"

    ref_dir = tmp_path / "ref_import"
    ref_dir.mkdir()
    import shutil
    shutil.copy(
        FIXTURES_DIR / "spa-blind-2026-07" / "Garage_61_60GBCK.csv",
        ref_dir / "Garage_61_60GBCK.csv",
    )
    result = CliRunner().invoke(cli_app, [
        "import", str(ref_dir), "--db", str(db_path),
        "--role", "reference", "--driver", "teammate JD",
        "--car", "GR86", "--track", "Spa-Francorchamps",
    ])
    assert result.exit_code == 0, result.output

    with Database.open(db_path) as db:
        lap_pk = int(
            db.conn.execute("SELECT lap_pk FROM laps WHERE role='reference'").fetchone()["lap_pk"]
        )
    client = TestClient(create_app(db_path, tmp_path / "config.toml"))
    return {"client": client, "db_path": db_path, "lap_pk": lap_pk}


def test_references_section_appears_in_the_payload_with_one_reference_lap(ref_env):
    refs = ref_env["client"].get(f"/api/cohorts/{SPA_SLUG}/payload").json()["references"]
    assert refs["n"] == 1 and refs["n_excluded"] == 0
    assert refs["envelope"]["n"] == 1
    assert refs["contributors"] == [{
        "lap_pk": ref_env["lap_pk"], "lap_id": "60GBCK", "driver": "teammate JD",
        "duration_s": refs["contributors"][0]["duration_s"],
        "lap_date": None, "excluded": False,
    }]


def test_exclude_then_include_reference_lap_through_the_api_recomputes_live(ref_env):
    c, db_path, lap_pk = ref_env["client"], ref_env["db_path"], ref_env["lap_pk"]

    r = c.post(f"/api/laps/{lap_pk}/exclude", json={"note": "not representative"})
    assert r.status_code == 200
    body = r.json()
    assert body["excluded"] == lap_pk
    assert body["exclusion"]["note"] == "not representative"
    with Database.open(db_path) as db:
        assert lap_pk in db.reference_exclusions()

    # Cascades immediately: the next payload fetch already reflects it, no
    # separate rebuild step (SPEC.md A39 decision 6).
    after = c.get(f"/api/cohorts/{SPA_SLUG}/payload").json()["references"]
    assert after["n"] == 0 and after["n_excluded"] == 1
    assert after["contributors"][0]["excluded"] is True  # still listed, marked

    r = c.request("DELETE", f"/api/laps/{lap_pk}/exclude")
    assert r.status_code == 200 and r.json()["included"] == lap_pk
    with Database.open(db_path) as db:
        assert lap_pk not in db.reference_exclusions()
    restored = c.get(f"/api/cohorts/{SPA_SLUG}/payload").json()["references"]
    assert restored["n"] == 1 and restored["n_excluded"] == 0

    # Un-excluding a lap that isn't excluded is a 404, not a silent no-op —
    # same discipline as clear_annotation.
    r = c.request("DELETE", f"/api/laps/{lap_pk}/exclude")
    assert r.status_code == 404
    assert "not excluded" in r.json()["detail"]


def test_exclude_reference_endpoint_404s_on_a_self_lap(ref_env):
    with Database.open(ref_env["db_path"]) as db:
        self_lap_pk = int(
            db.conn.execute(
                "SELECT lap_pk FROM laps WHERE role='self' LIMIT 1"
            ).fetchone()["lap_pk"]
        )
    r = ref_env["client"].post(f"/api/laps/{self_lap_pk}/exclude")
    assert r.status_code == 404
    assert "not a reference lap" in r.json()["detail"]


def test_exclude_reference_endpoint_404s_on_an_unknown_lap_pk(ref_env):
    r = ref_env["client"].post("/api/laps/999999/exclude")
    assert r.status_code == 404
    assert "no such lap" in r.json()["detail"]


def test_corner_reference_phases_endpoint_shape_and_exclusion(ref_env):
    c, lap_pk = ref_env["client"], ref_env["lap_pk"]
    r = c.get(f"/api/cohorts/{SPA_SLUG}/corners/C01/reference-phases")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"entry", "mid", "exit"}
    for phase_data in body.values():
        assert phase_data is None or set(phase_data) == {"n", "median_s", "best_s"}

    # At least one phase is populated by the one reference lap this fixture
    # carries; excluding it must zero that phase out too (same query
    # surface phase_history itself enforces).
    populated = [p for p, v in body.items() if v is not None]
    assert populated, "expected at least one phase to have reference data"
    assert all(body[p]["n"] == 1 for p in populated)

    c.post(f"/api/laps/{lap_pk}/exclude")
    after = c.get(f"/api/cohorts/{SPA_SLUG}/corners/C01/reference-phases").json()
    assert all(after[p] is None for p in populated)


def test_corner_reference_phases_empty_when_no_reference_laps(env):
    r = env["client"].get(f"/api/cohorts/{SPA_SLUG}/corners/C01/reference-phases")
    assert r.status_code == 200
    assert r.json() == {"entry": None, "mid": None, "exit": None}


def test_upload_driver_field_names_a_reference_laps_identity(tmp_path):
    """The gap R2 depends on: without a `driver` field, every uploaded
    reference lap would read as "owner" -- indistinguishable from the
    driver's own laps -- since the endpoint used to hardcode it."""
    db_path = tmp_path / "upload.db"
    app = create_app(db_path, tmp_path / "config.toml")
    client = TestClient(app)
    one_lap = FIXTURES_DIR / "Garage_61_HKWPXX.csv"
    ref_lap = FIXTURES_DIR / "spa-blind-2026-07" / "Garage_61_60GBCK.csv"

    with open(one_lap, "rb") as fh:
        client.post(
            "/api/laps/upload",
            files=[("files", (one_lap.name, fh, "text/csv"))],
            data={"car": "GR86", "track": "Spa-Francorchamps"},
        )
    with open(ref_lap, "rb") as fh:
        r = client.post(
            "/api/laps/upload",
            files=[("files", (ref_lap.name, fh, "text/csv"))],
            data={
                "car": "GR86", "track": "Spa-Francorchamps",
                "role": "reference", "driver": "teammate JD",
            },
        )
    assert r.status_code == 200
    with Database.open(db_path) as db:
        row = db.conn.execute(
            "SELECT driver FROM laps WHERE role='reference'"
        ).fetchone()
        assert row["driver"] == "teammate JD"
        self_row = db.conn.execute(
            "SELECT driver FROM laps WHERE role='self'"
        ).fetchone()
        assert self_row["driver"] == "owner"  # unchanged default when omitted
