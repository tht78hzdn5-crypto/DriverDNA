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
