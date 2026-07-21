"""DriverDNA command-line interface.

Commands arrive with their milestones (docs/SPEC.md):
  sync (M0b+) - import (M1) - corners (M1) - metrics (M2) - report (M4)
  coach (M4) - chat (M5) - history (M4) - model (M6) - coaching (M7)
"""

from pathlib import Path

import typer

from driverdna import __version__

app = typer.Typer(
    help="DriverDNA: deterministic driving-technique analysis over Garage61 telemetry.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Deterministic driving-technique analysis over Garage61 telemetry."""


@app.command()
def version() -> None:
    """Print the DriverDNA version."""
    typer.echo(__version__)


def _validate_lap_date(value: str) -> str:
    """YYYY-MM-DD or a full ISO8601 timestamp — the same `lap_date` shape
    `sync` writes from the API's `startTime`. Rejected loudly on a
    malformed value, never silently accepted: M6 trend sorts laps on this
    string, so a bad date would corrupt chronological ordering silently
    if let through."""
    from datetime import date as _date, datetime as _datetime

    try:
        _date.fromisoformat(value)
        return value
    except ValueError:
        pass
    try:
        _datetime.fromisoformat(value)
        return value
    except ValueError:
        typer.echo(
            f"error: date {value!r} is not valid (expected YYYY-MM-DD or a "
            "full ISO8601 timestamp)"
        )
        raise typer.Exit(code=2) from None


@app.command("import")
def import_cmd(
    directory: Path = typer.Argument(
        ..., help="Directory of Garage61 CSV exports (manifest.toml used if present)."
    ),
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    driver: str = typer.Option("owner", help="Driver label when no manifest."),
    car: str = typer.Option(None, help="Car label (required without manifest)."),
    track: str = typer.Option(None, help="Track label (required without manifest)."),
    role: str = typer.Option("self", help="Lap role: self or reference."),
    date: str = typer.Option(
        None, "--date",
        help="Lap date (YYYY-MM-DD or full ISO8601) applied to every imported "
        "file. With a manifest, a per-entry `date` overrides this for that "
        "entry only. Mirrors what `sync` sets from the API — enables M6 "
        "trend on manually-imported laps.",
    ),
) -> None:
    """Import lap CSVs: parse, segment, identify, measure, persist."""
    from driverdna.config import load_config
    from driverdna.db import Database
    from driverdna.ingest.contract import load_fixture_manifest
    from driverdna.ingest.parser import parse_garage61_filename
    from driverdna.pipeline import import_lap_file

    if date is not None:
        date = _validate_lap_date(date)

    config = load_config()
    manifest_path = directory / "manifest.toml"
    if manifest_path.exists():
        jobs = [
            {
                "path": directory / e["file"],
                "driver": e.get("driver", driver),
                "car": e["car"],
                "track": e["track"],
                "role": e["role"],
                "session_key": e.get("session"),
                "lap_date": _validate_lap_date(e["date"]) if "date" in e else date,
            }
            for e in load_fixture_manifest(directory)
        ]
    else:
        csv_files = sorted(directory.glob("*.csv"))
        if car and track:
            jobs = [
                {"path": p, "driver": driver, "car": car, "track": track, "role": role,
                 "lap_date": date}
                for p in csv_files
            ]
        else:
            # No manifest, no (complete) --car/--track: try auto-detecting
            # each file from the newer Garage61 export filename shape
            # (Garage_61__<driver>__<car>__<track>__<laptime>__<id>.csv,
            # ingest/parser.py's parse_garage61_filename). Never guessed past
            # what the filename actually states — a file that doesn't match
            # is a loud, itemized error, nothing partially imported.
            jobs = []
            unresolved: list[str] = []
            for p in csv_files:
                detected = parse_garage61_filename(p.name)
                if detected:
                    jobs.append({
                        "path": p, "driver": driver, "car": detected["car"],
                        "track": detected["track"], "role": role, "lap_date": date,
                        "_auto_detected": True,
                    })
                else:
                    unresolved.append(p.name)
            if not csv_files or unresolved:
                detail = (
                    f" (could not auto-detect car/track from {len(unresolved)} "
                    f"filename(s): {', '.join(unresolved[:5])}"
                    f"{', ...' if len(unresolved) > 5 else ''})"
                ) if unresolved else ""
                typer.echo(
                    "error: --car and --track are required without a manifest.toml"
                    + detail
                )
                raise typer.Exit(code=2)

    with Database.open(db_path) as db:
        for job in jobs:
            path = job.pop("path")
            auto_detected = job.pop("_auto_detected", False)
            result = import_lap_file(db, path, config=config, **job)
            detected_note = (
                f" (auto-detected from filename: {job['car']} @ {job['track']})"
                if auto_detected else ""
            )
            if result.status == "exists":
                typer.echo(f"{path.name}: already imported, skipped")
                continue
            if result.status == "duplicate":
                typer.echo(
                    f"{path.name}: DUPLICATE of already-imported lap "
                    f"{result.lap_pk} (identical telemetry) — skipped, not "
                    "double-counted"
                )
                continue
            matched = sum(1 for a in result.assigned if a)
            line = (
                f"{path.name}: lap {result.lap_pk}, corners "
                f"{matched}/{len(result.assigned)} matched{detected_note}"
            )
            if result.admitted:
                line += f"; ADMITTED to map: {', '.join(result.admitted)}"
            for corner_id, old, new in result.class_changes:
                line += f"; CLASS CHANGE {corner_id}: {old} -> {new}"
            typer.echo(line)
        evicted = db.enforce_retention(config.retention.raw_laps_per_cohort)
        if evicted:
            typer.echo(f"retention: evicted {evicted} raw lap blob(s); summaries kept")


@app.command()
def sync(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    driver: str = typer.Option("owner", help="Driver label."),
    car: str = typer.Option(None, help="Restrict to one car (by Garage61 name)."),
    track: str = typer.Option(None, help="Restrict to one track (by Garage61 name)."),
) -> None:
    """Incremental self-lap ingest from the Garage61 API (requires
    GARAGE61_TOKEN). Reference laps stay on `import` — M0b found other-
    drivers' laps aren't fetchable with this token (docs/garage61-api.md)."""
    from driverdna.config import load_config
    from driverdna.db import Database
    from driverdna.garage61.client import Garage61Client
    from driverdna.garage61.sync import sync_driver

    config = load_config()
    try:
        client = Garage61Client()
    except RuntimeError as e:
        typer.echo(f"error: {e}")
        raise typer.Exit(code=2) from None

    with Database.open(db_path) as db:
        summaries = sync_driver(db, client, driver=driver, config=config, car=car, track=track)
        if not summaries:
            typer.echo("no cohorts found (nothing driven yet, or --car/--track matched none)")
            raise typer.Exit(code=0)
        for s in summaries:
            typer.echo(
                f"{s.car} @ {s.track}: {s.laps_seen} seen, {s.laps_new} new"
            )
            for lap_id, reason in s.laps_skipped:
                typer.echo(f"  skipped {lap_id}: {reason}")
            for r in s.results:
                if r.status != "imported":
                    continue
                if r.admitted:
                    typer.echo(f"  ADMITTED to map: {', '.join(r.admitted)}")
                for corner_id, old, new in r.class_changes:
                    typer.echo(f"  CLASS CHANGE {corner_id}: {old} -> {new}")
        evicted = db.enforce_retention(config.retention.raw_laps_per_cohort)
        if evicted:
            typer.echo(f"retention: evicted {evicted} raw lap blob(s); summaries kept")


@app.command()
def metrics(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    out: Path = typer.Option(
        Path("docs/metrics-report.md"), help="Where to write the report."
    ),
) -> None:
    """M2 debug artifact: per-corner metric summaries and detector triggers."""
    from driverdna.db import Database
    from driverdna.metrics.report import build_metrics_report

    if not db_path.exists():
        typer.echo(f"error: no DB at {db_path} — run `driverdna import` first")
        raise typer.Exit(code=2)
    with Database.open(db_path) as db:
        out.write_text(build_metrics_report(db))
    typer.echo(f"wrote {out}")


@app.command()
def model(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    out: Path = typer.Option(
        Path("docs/driver-model-report.md"), help="Where to write the report."
    ),
) -> None:
    """M6 debug artifact: recompute + persist beliefs, per-fundamental score table."""
    from driverdna.config import load_config
    from driverdna.db import Database
    from driverdna.model.report import build_model_report

    if not db_path.exists():
        typer.echo(f"error: no DB at {db_path} — run `driverdna import` first")
        raise typer.Exit(code=2)
    config = load_config()
    with Database.open(db_path) as db:
        out.write_text(build_model_report(db, config))
    typer.echo(f"wrote {out}")


@app.command()
def coaching(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    out: Path = typer.Option(
        Path("docs/coaching-report.md"), help="Where to write the report."
    ),
) -> None:
    """M7 debug artifact: eligible/ranked/gap-banded coaching principles per cohort."""
    from driverdna.coaching.report import build_coaching_report
    from driverdna.config import load_config
    from driverdna.db import Database

    if not db_path.exists():
        typer.echo(f"error: no DB at {db_path} — run `driverdna import` first")
        raise typer.Exit(code=2)
    config = load_config()
    with Database.open(db_path) as db:
        out.write_text(build_coaching_report(db, config))
    typer.echo(f"wrote {out}")


@app.command()
def coach(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    cohort: str = typer.Option(
        None, help="Cohort as 'car:track' (defaults to the only cohort)."
    ),
    driver: str = typer.Option("owner", help="Driver label."),
    out_dir: Path = typer.Option(Path("reports"), help="Where the plan is written."),
) -> None:
    """Generate a one-shot coaching plan (requires ANTHROPIC_API_KEY)."""
    import re

    from driverdna.coach.payload import build_coach_payload
    from driverdna.coach.provider import (
        PROMPT_VERSION,
        SYSTEM_PROMPT,
        ClaudeCoachProvider,
    )
    from driverdna.coach.validate import (
        CoachValidationError,
        render_plan_markdown,
        validate_coach_output,
    )
    from driverdna.config import load_config
    from driverdna.db import Database
    from driverdna.report.payload import list_cohorts, to_normalized_json

    if not db_path.exists():
        typer.echo(f"error: no DB at {db_path} — run `driverdna import` first")
        raise typer.Exit(code=2)

    config = load_config()
    with Database.open(db_path) as db:
        cohorts = list_cohorts(db)
        if cohort:
            car, _, track = cohort.partition(":")
            cohorts = [c for c in cohorts if c["car"] == car and c["track"] == track]
        if len(cohorts) != 1:
            available = ", ".join(f"{c['car']}:{c['track']}" for c in cohorts) or "none"
            typer.echo(
                "error: specify one cohort with --cohort 'car:track' "
                f"(available: {available})"
            )
            raise typer.Exit(code=2)
        c = cohorts[0] | {"driver": driver}
        payload = build_coach_payload(db, **c, config=config)
        try:
            provider = ClaudeCoachProvider(config.coach.model, config.coach.max_tokens)
        except RuntimeError as e:
            typer.echo(f"error: {e}")
            raise typer.Exit(code=2) from None
        raw = provider.complete(SYSTEM_PROMPT, to_normalized_json(payload))
        try:
            output = validate_coach_output(raw, payload["report"])
        except CoachValidationError as e:
            typer.echo("coach output REJECTED by local validation:")
            for v in e.violations:
                typer.echo(f"  - {v}")
            raise typer.Exit(code=1) from None
        import json as _json

        db.store_coach_output(
            **c, payload_version=payload["report"]["payload_version"],
            prompt_version=PROMPT_VERSION, model=config.coach.model,
            output_json=_json.dumps(output, sort_keys=True),
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{c['car']}-{c['track']}").strip("-").lower()
        out = out_dir / f"coach-{slug}.md"
        out.write_text(render_plan_markdown(output, payload["report"]["cohort"]))
        typer.echo(f"wrote {out}")


@app.command()
def ui(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    config_path: Path = typer.Option(
        Path("driverdna.toml"), "--config", help="TOML config file."
    ),
    port: int = typer.Option(8710, help="Port on 127.0.0.1."),
) -> None:
    """Serve the local cockpit (API + built SPA) on 127.0.0.1."""
    try:
        import uvicorn
        from fastapi.staticfiles import StaticFiles

        from driverdna.ui.api import create_app
    except ModuleNotFoundError:
        typer.echo(
            "error: the UI extra is not installed — run "
            "`python3 -m pip install -e '.[ui]'`"
        )
        raise typer.Exit(code=2) from None

    application = create_app(db_path, config_path)
    static_dir = Path(__file__).parent / "ui" / "static"
    if static_dir.exists():
        application.mount("/", StaticFiles(directory=static_dir, html=True), name="spa")
    else:
        typer.echo("note: no built SPA found (ui/static missing) — serving API only")
    typer.echo(f"DriverDNA cockpit: http://127.0.0.1:{port}")
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")


def _demo_fixtures_dir() -> Path | None:
    """The bundled sample laps (tests/fixtures) live in the source tree, not
    the wheel — `demo` is the clone-and-run path. None if not a source
    checkout."""
    fixtures = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
    return fixtures if (fixtures / "manifest.toml").exists() else None


def _seed_demo_db(db, fixtures: Path, config) -> int:
    """Import the bundled sample laps into an empty demo DB (idempotent: a
    non-empty DB is left alone). Returns the lap count."""
    from driverdna.ingest.contract import load_fixture_manifest
    from driverdna.pipeline import import_lap_file

    existing = db.conn.execute("SELECT COUNT(*) AS n FROM laps").fetchone()["n"]
    if existing == 0:
        for e in load_fixture_manifest(fixtures):
            import_lap_file(
                db, fixtures / e["file"], config=config,
                driver=e.get("driver", "owner"), car=e["car"], track=e["track"],
                role=e["role"], session_key=e.get("session"),
            )
        db.enforce_retention(config.retention.raw_laps_per_cohort)
    return db.conn.execute("SELECT COUNT(*) AS n FROM laps").fetchone()["n"]


@app.command()
def demo(
    port: int = typer.Option(8710, help="Port on 127.0.0.1."),
    fresh: bool = typer.Option(
        False, help="Rebuild the demo DB from the bundled sample laps."
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Don't try to open a browser window."
    ),
) -> None:
    """One-command tour: seed the bundled sample laps and open the cockpit.

    No data or API key needed — imports the fixture laps into a demo DB under
    ~/.driverdna/ and serves the local cockpit at 127.0.0.1, opening your
    browser. The full `driverdna ui` is the same UI over your own data.
    """
    import threading

    from driverdna.config import load_config
    from driverdna.db import Database

    try:
        import uvicorn
        from fastapi.staticfiles import StaticFiles

        from driverdna.ui.api import create_app
    except ModuleNotFoundError:
        typer.echo(
            "error: the UI extra is not installed — run "
            "`python3 -m pip install -e '.[ui]'`"
        )
        raise typer.Exit(code=2) from None

    fixtures = _demo_fixtures_dir()
    if fixtures is None:
        typer.echo(
            "error: bundled sample laps not found (expected tests/fixtures/ "
            "in a source checkout). Import your own with `driverdna import` "
            "and launch `driverdna ui`."
        )
        raise typer.Exit(code=2)

    home = Path.home() / ".driverdna"
    home.mkdir(exist_ok=True)
    db_path, config_path = home / "demo.db", home / "demo.toml"
    if fresh and db_path.exists():
        db_path.unlink()

    config = load_config()
    with Database.open(db_path) as db:
        n = _seed_demo_db(db, fixtures, config)
    typer.echo(f"demo cockpit ready — {n} sample laps.")

    application = create_app(db_path, config_path)
    static_dir = Path(__file__).parent / "ui" / "static"
    if static_dir.exists():
        application.mount("/", StaticFiles(directory=static_dir, html=True), name="spa")

    url = f"http://127.0.0.1:{port}"
    typer.echo(f"DriverDNA cockpit: {url}  (Ctrl-C to stop)")
    if not no_browser:
        # Fire once the server is a beat from ready; harmless if headless.
        threading.Timer(1.2, lambda: _try_open_browser(url)).start()
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")


def _try_open_browser(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:  # headless / no display — the URL is printed anyway
        pass


@app.command()
def chat(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    cohort: str = typer.Option(
        None, help="Cohort as 'car:track' (defaults to the only cohort)."
    ),
    driver: str = typer.Option("owner", help="Driver label."),
    config_path: Path = typer.Option(
        Path("driverdna.toml"), "--config", help="TOML config file (ConfigStore target)."
    ),
) -> None:
    """Interactive grounded coaching chat (requires ANTHROPIC_API_KEY)."""
    import uuid

    from driverdna.chat.session import ChatSession, ClaudeChatProvider
    from driverdna.config import ConfigStore, load_config
    from driverdna.db import Database
    from driverdna.report.payload import list_cohorts

    if not db_path.exists():
        typer.echo(f"error: no DB at {db_path} — run `driverdna import` first")
        raise typer.Exit(code=2)
    config = load_config(config_path)
    with Database.open(db_path) as db:
        cohorts = list_cohorts(db)
        if cohort:
            car, _, track = cohort.partition(":")
            cohorts = [c for c in cohorts if c["car"] == car and c["track"] == track]
        if len(cohorts) != 1:
            available = ", ".join(f"{c['car']}:{c['track']}" for c in cohorts) or "none"
            typer.echo(
                f"error: specify one cohort with --cohort 'car:track' (available: {available})"
            )
            raise typer.Exit(code=2)
        try:
            provider = ClaudeChatProvider(config.coach.model, config.coach.max_tokens)
        except RuntimeError as e:
            typer.echo(f"error: {e}")
            raise typer.Exit(code=2) from None
        session = ChatSession(
            db=db, store=ConfigStore(config_path, db), provider=provider,
            **cohorts[0], config=config, session_id=uuid.uuid4().hex[:12],
        )
        typer.echo(
            "DriverDNA chat — grounded in your deterministic findings. "
            "/confirm N applies a staged config change; /quit exits."
        )
        while True:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text in ("/quit", "/exit"):
                break
            if text.startswith("/confirm"):
                try:
                    index = int(text.split()[1])
                    effects = session.confirm(index)
                    applied = effects["config_applied"]
                    typer.echo(
                        f"applied: {applied['key']} {applied['old']} -> "
                        f"{applied['new']} (change #{applied['change_pk']}, reversible)"
                    )
                except (IndexError, ValueError) as e:
                    typer.echo(f"error: {e}")
                continue
            result = session.ask(text)
            if "error" in result:
                typer.echo(f"[rejected] {result['error']}")
            else:
                typer.echo(result["text"])
                if result["staged"]:
                    typer.echo(
                        f"(staged config proposals awaiting /confirm: "
                        f"{', '.join(p['key'] for p in result['staged'])})"
                    )


@app.command()
def history(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
) -> None:
    """Show cohorts, coach runs, and config changes on record."""
    from driverdna.db import Database
    from driverdna.report.payload import list_cohorts

    if not db_path.exists():
        typer.echo(f"error: no DB at {db_path} — run `driverdna import` first")
        raise typer.Exit(code=2)
    with Database.open(db_path) as db:
        for c in list_cohorts(db):
            n = db.conn.execute(
                """SELECT COUNT(*) n FROM laps WHERE role='self'
                   AND driver=? AND car=? AND track=?""",
                (c["driver"], c["car"], c["track"]),
            ).fetchone()["n"]
            n_ref = db.conn.execute(
                "SELECT COUNT(*) n FROM laps WHERE role='reference' AND car=? AND track=?",
                (c["car"], c["track"]),
            ).fetchone()["n"]
            typer.echo(
                f"{c['driver']} / {c['car']} @ {c['track']}: {n} self laps, "
                f"{n_ref} reference laps"
            )
            for h in db.coach_history(**c):
                titles = ", ".join(t for t in h["plan_titles"] if t) or "(untitled)"
                typer.echo(f"  coach #{h['output_pk']}: {titles}")
        changes = db.conn.execute(
            "SELECT * FROM config_history ORDER BY change_pk"
        ).fetchall()
        for ch in changes:
            typer.echo(
                f"config: {ch['key']} {ch['old_value']} -> {ch['new_value']} "
                f"({ch['source']})"
            )


@app.command()
def report(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    out_dir: Path = typer.Option(Path("reports"), help="Output directory."),
    cohort: str = typer.Option(
        None, help="Restrict to one cohort as 'car:track' (default: all)."
    ),
) -> None:
    """Generate Markdown + JSON + self-contained HTML reports."""
    import re

    from driverdna.config import load_config
    from driverdna.db import Database
    from driverdna.report.builder import (
        render_cohort_html,
        render_cohort_markdown,
        render_driver_html,
        render_driver_markdown,
    )
    from driverdna.report.payload import (
        build_cohort_payload,
        build_driver_payload,
        list_cohorts,
        to_normalized_json,
    )

    if not db_path.exists():
        typer.echo(f"error: no DB at {db_path} — run `driverdna import` first")
        raise typer.Exit(code=2)

    def slug(text: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()

    config = load_config()
    out_dir.mkdir(parents=True, exist_ok=True)
    with Database.open(db_path) as db:
        cohorts = list_cohorts(db)
        if cohort:
            car, _, track = cohort.partition(":")
            cohorts = [c for c in cohorts if c["car"] == car and c["track"] == track]
            if not cohorts:
                typer.echo(f"error: no cohort matching {cohort!r}")
                raise typer.Exit(code=2)
        for c in cohorts:
            payload = build_cohort_payload(db, **c, config=config)
            base = out_dir / f"{slug(c['car'])}-{slug(c['track'])}"
            base.with_suffix(".md").write_text(render_cohort_markdown(payload))
            base.with_suffix(".json").write_text(to_normalized_json(payload))
            base.with_suffix(".html").write_text(render_cohort_html(payload))
            typer.echo(f"wrote {base}.{{md,json,html}}")
        driver_payload = build_driver_payload(db, config)
        (out_dir / "driver.md").write_text(render_driver_markdown(driver_payload))
        (out_dir / "driver.json").write_text(to_normalized_json(driver_payload))
        (out_dir / "driver.html").write_text(render_driver_html(driver_payload))
        typer.echo(f"wrote {out_dir}/driver.{{md,json,html}}")


@app.command()
def attribution(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    out: Path = typer.Option(
        Path("docs/attribution-report.md"), help="Where to write the report."
    ),
) -> None:
    """M3 debug artifact: canonical windows, baselines, losses, findings."""
    from driverdna.attribution.report import build_attribution_report
    from driverdna.config import load_config
    from driverdna.db import Database

    if not db_path.exists():
        typer.echo(f"error: no DB at {db_path} — run `driverdna import` first")
        raise typer.Exit(code=2)
    with Database.open(db_path) as db:
        out.write_text(build_attribution_report(db, load_config()))
    typer.echo(f"wrote {out}")


@app.command()
def incidents(
    db_path: Path = typer.Option(Path("driverdna.db"), "--db", help="SQLite DB path."),
    out: Path = typer.Option(
        Path("docs/incidents-report.md"), help="Where to write the report."
    ),
) -> None:
    """Incident artifact: detected spins/offs/near-stops + their mechanism."""
    from driverdna.db import Database
    from driverdna.incidents.report import build_incidents_report

    if not db_path.exists():
        typer.echo(f"error: no DB at {db_path} — run `driverdna import` first")
        raise typer.Exit(code=2)
    with Database.open(db_path) as db:
        out.write_text(build_incidents_report(db))
    typer.echo(f"wrote {out}")


@app.command()
def corners(
    fixtures_dir: Path = typer.Option(
        Path("tests/fixtures"), help="Directory holding the fixture CSVs and manifest.toml."
    ),
    out: Path = typer.Option(
        Path("docs/corners-report.md"), help="Where to write the report."
    ),
) -> None:
    """M1 debug artifact: corner map, classes, and per-lap landmarks."""
    from driverdna.config import load_config
    from driverdna.corners.report import build_corners_report

    out.write_text(build_corners_report(fixtures_dir, load_config()))
    typer.echo(f"wrote {out}")


@app.command("schema-report")
def schema_report(
    fixtures_dir: Path = typer.Option(
        Path("tests/fixtures"), help="Directory holding the fixture CSVs and manifest.toml."
    ),
    out: Path = typer.Option(
        Path("docs/schema-report.md"), help="Where to write the report."
    ),
) -> None:
    """Generate the M0a schema-lock report from the fixture exports."""
    from driverdna.ingest.contract import build_schema_report

    out.write_text(build_schema_report(fixtures_dir))
    typer.echo(f"wrote {out}")
