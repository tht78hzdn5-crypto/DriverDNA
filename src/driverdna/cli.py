"""DriverDNA command-line interface.

Commands arrive with their milestones (docs/SPEC.md):
  sync (M0b+) - import (M1) - corners (M1) - metrics (M2) - report (M4)
  coach (M4) - chat (M5) - history (M4)
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
) -> None:
    """Import lap CSVs: parse, segment, identify, measure, persist."""
    from driverdna.config import load_config
    from driverdna.db import Database
    from driverdna.ingest.contract import load_fixture_manifest
    from driverdna.pipeline import import_lap_file

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
            }
            for e in load_fixture_manifest(directory)
        ]
    else:
        if not car or not track:
            typer.echo("error: --car and --track are required without a manifest.toml")
            raise typer.Exit(code=2)
        jobs = [
            {"path": p, "driver": driver, "car": car, "track": track, "role": role}
            for p in sorted(directory.glob("*.csv"))
        ]

    with Database.open(db_path) as db:
        for job in jobs:
            path = job.pop("path")
            result = import_lap_file(db, path, config=config, **job)
            if not result.was_new:
                typer.echo(f"{path.name}: already imported, skipped")
                continue
            matched = sum(1 for a in result.assigned if a)
            line = f"{path.name}: lap {result.lap_pk}, corners {matched}/{len(result.assigned)} matched"
            if result.admitted:
                line += f"; ADMITTED to map: {', '.join(result.admitted)}"
            for corner_id, old, new in result.class_changes:
                line += f"; CLASS CHANGE {corner_id}: {old} -> {new}"
            typer.echo(line)
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
