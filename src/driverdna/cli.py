"""DriverDNA command-line interface.

Commands arrive with their milestones (docs/SPEC.md):
  sync (M0b+) - import (M1) - corners (M1) - metrics (M2) - report (M4)
  coach (M4) - chat (M5) - history (M4) - model (M6) - coaching (M7)
"""

import os
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


def _store(db_path: str | None) -> str:
    """Resolve `--db` against the environment. See store.resolve_store for
    why there is deliberately no bare DATABASE_URL fallback (and no silent
    fallback for an empty explicit --db, either)."""
    from driverdna.store import resolve_store

    try:
        return resolve_store(db_path)
    except ValueError as e:
        typer.echo(f"error: {e}")
        raise typer.Exit(code=2) from None


def _require_store(db_path: str | None) -> str:
    """Same, but for commands that read an existing store rather than create
    one. A missing SQLite file is reported by path; a hosted store has no
    file to stat, so it reports connection trouble instead — never the raw
    URL, which carries the password."""
    from driverdna.store import missing_reason

    target = _store(db_path)
    reason = missing_reason(target)
    if reason:
        typer.echo(f"error: {reason} — run `driverdna import` first")
        raise typer.Exit(code=2)
    return target


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


def _validate_after(value: str) -> str:
    """Normalise `sync --after` to the RFC3339 the API's `after` parameter
    documents (`format: date-time`).

    A bare `YYYY-MM-DD` becomes midnight UTC, and a naive timestamp is read
    as UTC — stated here and in the flag's help rather than left implicit.
    This only moves a *filter boundary* by at most a few hours; no lap's
    stored `lap_date` is affected, since that always comes from the API's
    own `startTime`. Validated locally because this API silently ignores
    query values it cannot parse, which would turn a typo'd date into a
    full, unbounded backfill with no error.
    """
    from datetime import UTC, date as _date, datetime as _datetime

    validated = _validate_lap_date(value)
    try:
        parsed = _datetime.fromisoformat(validated)
    except ValueError:
        parsed = _datetime.combine(
            _date.fromisoformat(validated), _datetime.min.time()
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat().replace("+00:00", "Z")


@app.command("import")
def import_cmd(
    directory: Path = typer.Argument(
        ..., help="Directory of Garage61 CSV exports (manifest.toml used if present)."
    ),
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    driver: str = typer.Option("owner", help="Driver label when no manifest."),
    car: str = typer.Option(
        None, help="Car label. Omit to auto-detect from each Garage61 export "
                   "filename; give it to apply one car to every file."),
    track: str = typer.Option(
        None, help="Track label. Omit to auto-detect from each Garage61 export "
                   "filename; give it to apply one track to every file."),
    role: str = typer.Option("self", help="Lap role: self or reference."),
    date: str = typer.Option(
        None, "--date",
        help="Lap date (YYYY-MM-DD or full ISO8601) applied to every imported "
        "file. With a manifest, a per-entry `date` overrides this for that "
        "entry only. Mirrors what `sync` sets from the API — enables M6 "
        "trend on manually-imported laps.",
    ),
    session: str = typer.Option(
        None, "--session",
        help="Session label applied to every imported file. With a manifest, "
        "a per-entry `session` overrides this for that entry only. Mirrors "
        "what `sync` sets from the API — enables the min_sessions gate "
        "and within-session repeatability.",
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
                "session_key": e.get("session", session),
                "lap_date": _validate_lap_date(e["date"]) if "date" in e else date,
            }
            for e in load_fixture_manifest(directory)
        ]
    else:
        csv_files = sorted(directory.glob("*.csv"))
        car = car.strip() if car else None
        track = track.strip() if track else None
        # No manifest: --car/--track are independently optional and either one
        # on its own is a working manual override. A flag that is given applies
        # to every file; a flag that is omitted is auto-detected per file from
        # either newer Garage61 export filename shape (ingest/parser.py's
        # parse_garage61_filename). So a future filename rename never strands
        # the driver — passing just the flag the filename no longer states is
        # enough. Never guessed past what the filename actually states: a file
        # still missing a field is a loud, itemized error naming that field,
        # nothing partially imported.
        jobs = []
        unresolved: list[str] = []
        for p in csv_files:
            file_car, file_track = car, track
            detected = (
                parse_garage61_filename(p.name)
                if file_car is None or file_track is None
                else None
            )
            if detected:
                file_car = file_car or detected["car"]
                file_track = file_track or detected["track"]
            if file_car is None or file_track is None:
                missing = " and ".join(
                    n for n, v in (("car", file_car), ("track", file_track)) if v is None
                )
                unresolved.append(f"{p.name} (missing {missing})")
                continue
            jobs.append({
                "path": p, "driver": driver, "car": file_car, "track": file_track,
                "role": role, "session_key": session, "lap_date": date,
                # Only the fields that actually came from the filename, so the
                # per-file note never calls a value the driver typed "detected".
                "_detected": () if detected is None else tuple(
                    n for n, given in (("car", car), ("track", track)) if given is None
                ),
            })
        if not csv_files:
            typer.echo(f"error: no .csv files in {directory}")
            raise typer.Exit(code=2)
        if unresolved:
            typer.echo(
                f"error: could not resolve car/track for {len(unresolved)} "
                f"file(s): {', '.join(unresolved[:5])}"
                f"{', ...' if len(unresolved) > 5 else ''}\n"
                "  auto-detect reads a Garage61 export filename shaped\n"
                "  'Garage 61 - <driver> - <car> - <track> - <laptime> - <id>.csv' or\n"
                "  'Garage_61__<driver>__<car>__<track>__<laptime>__<id>.csv'\n"
                "  otherwise pass the missing field (--car/--track); it then "
                "applies to every file"
            )
            raise typer.Exit(code=2)

    with Database.open(_store(db_path)) as db:
        # Pre-flight (A34): the first lap in a cohort BUILDS its corner map, so
        # a reference lap can never be that lap — the map is the coordinate
        # system every later self measurement is taken in. Checked for the whole
        # run up front, itemized, nothing imported, same contract as an
        # unresolvable car/track above. A self lap earlier in this same run
        # counts, so a mixed manifest (self laps then a reference lap) passes.
        founded = {
            (j["car"], j["track"])
            for j in jobs
            if db.load_corner_map(car=j["car"], track=j["track"]) is not None
        }
        orphans: list[str] = []
        for job in jobs:
            key = (job["car"], job["track"])
            if job.get("role", "self") == "self":
                founded.add(key)
            elif key not in founded:
                orphans.append(f"{job['path'].name} ({key[0]} @ {key[1]})")
        if orphans:
            typer.echo(
                f"error: {len(orphans)} reference lap(s) would be the first lap "
                f"in their cohort: {', '.join(orphans[:5])}"
                f"{', ...' if len(orphans) > 5 else ''}\n"
                "  The first lap in a cohort builds the corner map — every\n"
                "  corner's position and every phase window. Built from another\n"
                "  driver's line, that map becomes the coordinate system your\n"
                "  own laps are then measured in.\n"
                "  Import at least one of your own laps in that car/track first.\n"
                "  Nothing has been imported."
            )
            raise typer.Exit(code=2)

        for job in jobs:
            path = job.pop("path")
            detected = job.pop("_detected", ())
            result = import_lap_file(db, path, config=config, **job)
            if detected == ("car", "track"):
                detected_note = (
                    f" (auto-detected from filename: {job['car']} @ {job['track']})"
                )
            elif detected:
                detected_note = (
                    f" ({detected[0]} auto-detected from filename: {job[detected[0]]})"
                )
            else:
                detected_note = ""
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
        # Checked here because import is where a divergent label is created —
        # catching it now costs one re-import, catching it later costs a
        # rebuilt history (A27).
        from driverdna.report.payload import list_cohorts as _list_cohorts

        _warn_label_drift(_list_cohorts(db))


@app.command()
def sync(
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    driver: str = typer.Option("owner", help="Driver label."),
    car: str = typer.Option(None, help="Restrict to one car (by Garage61 name)."),
    track: str = typer.Option(None, help="Restrict to one track (by Garage61 name)."),
    clean_only: bool = typer.Option(
        False, "--clean-only",
        help="Ask the API for clean laps only. Default is to include unclean "
             "laps: a spin or an off is measured, not filtered (A19).",
    ),
    after: str = typer.Option(
        None, "--after",
        help="Only laps driven after this date (YYYY-MM-DD or ISO8601; a bare "
             "date means midnight UTC, a naive timestamp is read as UTC). "
             "Filters on when the lap was DRIVEN, not when it was synced.",
    ),
    max_age_days: int = typer.Option(
        None, "--max-age-days",
        help="Only laps driven in the last N days. Negative values select "
             "seasons instead (-1 current, -2 current+previous, -3, -4).",
    ),
) -> None:
    """Incremental self-lap ingest from the Garage61 API (requires
    GARAGE61_TOKEN). Reference laps stay on `import` — M0b found other-
    drivers' laps aren't fetchable with this token (docs/garage61-api.md).

    Since A28 this pulls EVERY lap per cohort (`group=none`), not one
    personal best per cohort, so the first run after upgrading may fetch a
    lot of laps. It is resumable: an already-synced lap never costs a CSV
    call. Use --after/--max-age-days to bound a first backfill.
    """
    from driverdna.config import load_config
    from driverdna.db import Database
    from driverdna.garage61.client import Garage61Client
    from driverdna.garage61.sync import sync_driver

    config = load_config()
    if after is not None:
        after = _validate_after(after)
    try:
        client = Garage61Client()
    except RuntimeError as e:
        typer.echo(f"error: {e}")
        raise typer.Exit(code=2) from None

    with Database.open(_store(db_path)) as db:
        summaries = sync_driver(
            db, client, driver=driver, config=config, car=car, track=track,
            unclean=not clean_only, after=after, max_age_days=max_age_days,
        )
        if not summaries:
            typer.echo("no cohorts found (nothing driven yet, or --car/--track matched none)")
            raise typer.Exit(code=0)
        for s in summaries:
            typer.echo(
                f"{s.car} @ {s.track}: {s.laps_seen} seen, {s.laps_new} new"
            )
            if s.laps_without_telemetry:
                typer.echo(
                    f"  {s.laps_without_telemetry} lap(s) listed but their telemetry "
                    f"is not viewable by this token (canViewTelemetry=false) — "
                    f"metadata only, nothing imported for them"
                )
            if s.foreign_rows:
                typer.echo(
                    f"  note: paged {s.foreign_rows} other-driver row(s) — the "
                    f"server-side drivers=me scope did not apply; they were "
                    f"discarded locally, nothing of theirs was fetched"
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
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    out: Path = typer.Option(
        Path("docs/metrics-report.md"), help="Where to write the report."
    ),
) -> None:
    """M2 debug artifact: per-corner metric summaries and detector triggers."""
    from driverdna.db import Database
    from driverdna.metrics.report import build_metrics_report

    db_path = _require_store(db_path)
    with Database.open(db_path) as db:
        out.write_text(build_metrics_report(db))
    typer.echo(f"wrote {out}")


@app.command()
def model(
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    out: Path = typer.Option(
        Path("docs/driver-model-report.md"), help="Where to write the report."
    ),
) -> None:
    """M6 debug artifact: recompute + persist beliefs, per-fundamental score table."""
    from driverdna.config import load_config
    from driverdna.db import Database
    from driverdna.model.report import build_model_report

    db_path = _require_store(db_path)
    config = load_config()
    with Database.open(db_path) as db:
        out.write_text(build_model_report(db, config))
    typer.echo(f"wrote {out}")


@app.command()
def census(
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    out: Path = typer.Option(
        Path("docs/census-report.md"), help="Where to write the report."
    ),
) -> None:
    """Corpus readiness: have-vs-need for every gate, and what to add next."""
    from driverdna.census import build_census_report
    from driverdna.config import load_config
    from driverdna.db import Database

    db_path = _require_store(db_path)
    config = load_config()
    with Database.open(db_path) as db:
        out.write_text(build_census_report(db, config))
    typer.echo(f"wrote {out}")


@app.command()
def coaching(
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    out: Path = typer.Option(
        Path("docs/coaching-report.md"), help="Where to write the report."
    ),
) -> None:
    """M7 debug artifact: eligible/ranked/gap-banded coaching principles per cohort."""
    from driverdna.coaching.report import build_coaching_report
    from driverdna.config import load_config
    from driverdna.db import Database

    db_path = _require_store(db_path)
    config = load_config()
    with Database.open(db_path) as db:
        out.write_text(build_coaching_report(db, config))
    typer.echo(f"wrote {out}")


@app.command()
def coach(
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    cohort: str = typer.Option(
        None, help="Cohort as 'car:track' (defaults to the only cohort)."
    ),
    driver: str = typer.Option("owner", help="Driver label."),
    out_dir: Path = typer.Option(Path("reports"), help="Where the plan is written."),
    config_path: Path = typer.Option(
        Path("driverdna.toml"), "--config", help="TOML config file (ConfigStore target)."
    ),
) -> None:
    """Generate a one-shot coaching plan (requires ANTHROPIC_API_KEY or
    GEMINI_API_KEY, per config.coach.provider)."""
    import re

    from driverdna.coach.payload import build_coach_payload
    from driverdna.coach.provider import PROMPT_VERSION, SYSTEM_PROMPT, make_coach_provider
    from driverdna.coach.validate import (
        CoachValidationError,
        render_plan_markdown,
        validate_coach_output,
    )
    from driverdna.config import load_config
    from driverdna.db import Database
    from driverdna.report.payload import list_cohorts, to_normalized_json

    db_path = _require_store(db_path)

    config = load_config(config_path)
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
            provider = make_coach_provider(config)
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

        model_used = (
            config.coach.gemini_model if config.coach.provider == "gemini" else config.coach.model
        )
        db.store_coach_output(
            **c, payload_version=payload["report"]["payload_version"],
            prompt_version=PROMPT_VERSION, model=model_used,
            provider=config.coach.provider,
            output_json=_json.dumps(output, sort_keys=True),
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{c['car']}-{c['track']}").strip("-").lower()
        out = out_dir / f"coach-{slug}.md"
        out.write_text(render_plan_markdown(output, payload["report"]["cohort"]))
        typer.echo(f"wrote {out}")


def _is_loopback(host: str) -> bool:
    """True only for addresses that cannot be reached from another machine.

    Fails closed: a name this cannot parse (a DNS hostname, a typo, an empty
    string) is treated as exposed. Guessing the other way is exactly how an
    unauthenticated instrument ends up on the internet, and the cost of being
    wrong in this direction is only that the driver sets a passphrase.
    """
    import ipaddress

    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@app.command()
def ui(
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    config_path: Path = typer.Option(
        Path("driverdna.toml"), "--config", help="TOML config file."
    ),
    port: int = typer.Option(
        int(os.environ.get("PORT", "8710")),
        help="Listen port. Defaults to $PORT if set, else 8710.",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        help="Bind address. Use 0.0.0.0 for hosted/container deployments — "
             "which requires DRIVERDNA_SESSION_SECRET (or DRIVERDNA_ACCESS_TOKEN) to be set.",
    ),
    behind_proxy: bool = typer.Option(
        False, "--behind-proxy",
        help="A reverse proxy (Cloudflare Tunnel, nginx, Caddy) sits in "
             "front of this process on the same host — e.g. the Oracle VM "
             "target (SPEC.md A41). Applies the auth interlock regardless "
             "of bind address (a loopback bind behind an unnoticed proxy is "
             "otherwise reachable by anyone, unauthenticated), and wires "
             "uvicorn to trust X-Forwarded-* only from 127.0.0.1 — the "
             "proxy's own address, never a wildcard. Defaults to "
             "$DRIVERDNA_BEHIND_PROXY (1/true/yes).",
    ),
) -> None:
    """Serve the cockpit (API + built SPA)."""
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

    from driverdna.ui import auth

    session_secret = auth.session_secret_from_env()
    google_client_id = auth.google_client_id_from_env()
    google_client_secret = auth.google_client_secret_from_env()
    smtp_config = auth.smtp_config_from_env()
    # Read at call time (not baked into the Option default above) so the env
    # var is honored even when it's set after this module was imported —
    # matching how every other secret here is read lazily from the process
    # environment rather than captured once at import time.
    behind_proxy = behind_proxy or (
        os.environ.get("DRIVERDNA_BEHIND_PROXY", "").strip().lower() in ("1", "true", "yes")
    )

    # The fail-closed interlock (docs/DEPLOY-SPEC.md H1; SPEC.md A41): a
    # non-loopback bind, OR a loopback bind with a reverse proxy declared in
    # front of it, must have a session-signing secret, full stop. The
    # loopback+behind_proxy case matters because the interlock otherwise
    # keys off bind address alone — a reverse proxy in front of a
    # loopback-bound instance defeats that silently, since the bind looks
    # safe while every request through the proxy is actually reachable from
    # wherever the proxy is (docs/VM-MIGRATION.md §3.1). This also used to
    # fall back to an ephemeral, process-local secret so a container would
    # still start — retired 2026-08-05 (owner-confirmed) because on a
    # restart-prone host that meant every reboot/redeploy silently rotated
    # the key and signed everyone out with nothing in the logs to explain
    # why (docs/VM-MIGRATION.md §1.3/§3.7). Refusing loudly here is strictly
    # better than starting into a state that will fail confusingly later.
    if (behind_proxy or not _is_loopback(host)) and session_secret is None:
        reason = "--behind-proxy is set" if behind_proxy and _is_loopback(host) \
            else f"binding a non-loopback address ({host})"
        typer.echo(
            f"error: {auth.SESSION_SECRET_ENV} (or DRIVERDNA_ACCESS_TOKEN) "
            f"must be set — refusing to start unauthenticated ({reason}). "
            "Set the env var, or drop --behind-proxy / bind loopback with "
            "nothing in front of it for local-only use."
        )
        raise typer.Exit(code=2)

    resolved = _store(db_path)
    from driverdna.store import describe
    typer.echo(
        f"starting: host={host} port={port} "
        f"db={describe(resolved)} "
        f"auth={'yes' if session_secret else 'no'} "
        f"behind_proxy={'yes' if behind_proxy else 'no'}"
    )
    application = create_app(
        resolved, config_path, session_secret=session_secret,
        google_client_id=google_client_id, google_client_secret=google_client_secret,
        smtp_config=smtp_config, behind_proxy=behind_proxy,
    )
    static_dir = Path(__file__).parent / "ui" / "static"
    if static_dir.exists():
        application.mount("/", StaticFiles(directory=static_dir, html=True), name="spa")
    else:
        typer.echo("note: no built SPA found (ui/static missing) — serving API only")
    typer.echo(f"DriverDNA cockpit: http://{host}:{port}")
    # proxy_headers/forwarded_allow_ips made explicit rather than relying on
    # uvicorn's own defaults (which happen to already resolve to
    # True/"127.0.0.1") — a security-relevant trust boundary should be an
    # intentional, tested contract in this codebase, not an inherited
    # library default that could change under a version bump.
    if behind_proxy:
        uvicorn.run(
            application, host=host, port=port, log_level="warning",
            proxy_headers=True, forwarded_allow_ips="127.0.0.1",
        )
    else:
        uvicorn.run(
            application, host=host, port=port, log_level="warning",
            proxy_headers=False,
        )


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

    existing = db.conn.execute("SELECT COUNT(*) AS n FROM laps WHERE owner_user_pk=?", (db.user_pk,)).fetchone()["n"]
    if existing == 0:
        for e in load_fixture_manifest(fixtures):
            import_lap_file(
                db, fixtures / e["file"], config=config,
                driver=e.get("driver", "owner"), car=e["car"], track=e["track"],
                role=e["role"], session_key=e.get("session"),
            )
        db.enforce_retention(config.retention.raw_laps_per_cohort)
    return db.conn.execute("SELECT COUNT(*) AS n FROM laps WHERE owner_user_pk=?", (db.user_pk,)).fetchone()["n"]


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

    # Loopback-only, bundled sample laps — no interlock is needed here and
    # `--host` deliberately does not exist on this command. The passphrase is
    # still honoured when one is configured, so `demo` and `ui` never disagree
    # about whether this machine requires a login.
    from driverdna.ui import auth

    application = create_app(
        db_path, config_path, session_secret=auth.session_secret_from_env(),
        google_client_id=auth.google_client_id_from_env(),
        google_client_secret=auth.google_client_secret_from_env(),
        smtp_config=auth.smtp_config_from_env()
    )
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
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    cohort: str = typer.Option(
        None, help="Cohort as 'car:track' (defaults to the only cohort)."
    ),
    driver: str = typer.Option("owner", help="Driver label."),
    config_path: Path = typer.Option(
        Path("driverdna.toml"), "--config", help="TOML config file (ConfigStore target)."
    ),
) -> None:
    """Interactive grounded coaching chat (requires ANTHROPIC_API_KEY or
    GEMINI_API_KEY, per config.coach.provider)."""
    import uuid

    from driverdna.chat.session import ChatSession, make_chat_provider
    from driverdna.config import ConfigStore, load_config
    from driverdna.db import Database
    from driverdna.report.payload import list_cohorts

    db_path = _require_store(db_path)
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
            provider = make_chat_provider(config)
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
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
) -> None:
    """Show cohorts, coach runs, and config changes on record."""
    from driverdna.db import Database
    from driverdna.report.payload import list_cohorts

    db_path = _require_store(db_path)
    with Database.open(db_path) as db:
        for c in list_cohorts(db):
            n = db.conn.execute(
                """SELECT COUNT(*) n FROM laps WHERE role='self'
                   AND driver=? AND car=? AND track=? AND owner_user_pk=?""",
                (c["driver"], c["car"], c["track"], db.user_pk),
            ).fetchone()["n"]
            n_ref = db.conn.execute(
                "SELECT COUNT(*) n FROM laps WHERE role='reference' AND car=? AND track=? AND owner_user_pk=?",
                (c["car"], c["track"], db.user_pk),
            ).fetchone()["n"]
            typer.echo(
                f"{c['driver']} / {c['car']} @ {c['track']}: {n} self laps, "
                f"{n_ref} reference laps"
            )
            for h in db.coach_history(**c):
                titles = ", ".join(t for t in h["plan_titles"] if t) or "(untitled)"
                typer.echo(f"  coach #{h['output_pk']} ({h['provider']}): {titles}")
        changes = db.conn.execute(
            "SELECT * FROM config_history ORDER BY change_pk"
        ).fetchall()
        for ch in changes:
            typer.echo(
                f"config: {ch['key']} {ch['old_value']} -> {ch['new_value']} "
                f"({ch['source']})"
            )
        _warn_label_drift(list_cohorts(db))


def _warn_label_drift(cohorts: list[dict[str, str]]) -> None:
    """Surface cohorts that look like one cohort spelled two ways (A27).

    Reported, never repaired: a cohort key is load-bearing for evidence IDs,
    and only the driver knows which label is right.
    """
    from driverdna.cohorts import find_label_drift

    pairs = find_label_drift(cohorts)
    if not pairs:
        return
    typer.echo("")
    typer.echo(
        f"warning: {len(pairs)} cohort pair(s) look like the same cohort under "
        "two labels."
    )
    for p in pairs:
        typer.echo(f"  {p.left[0]} @ {p.left[1]}")
        typer.echo(f"  {p.right[0]} @ {p.right[1]}")
        typer.echo(f"    -> {p.describe()}")
    typer.echo(
        "  Split cohorts compute every baseline, trend and consistency number\n"
        "  from half the laps, silently. `sync` labels a track with the API's\n"
        "  variant (\"Track (Config)\"); a manual import uses the filename,\n"
        "  which has none. To merge, re-import the affected laps with an\n"
        "  explicit --car/--track matching the label you want to keep.\n"
        "  Nothing has been changed automatically."
    )


@app.command()
def report(
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
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

    db_path = _require_store(db_path)

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
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    out: Path = typer.Option(
        Path("docs/attribution-report.md"), help="Where to write the report."
    ),
) -> None:
    """M3 debug artifact: canonical windows, baselines, losses, findings."""
    from driverdna.attribution.report import build_attribution_report
    from driverdna.config import load_config
    from driverdna.db import Database

    db_path = _require_store(db_path)
    with Database.open(db_path) as db:
        out.write_text(build_attribution_report(db, load_config()))
    typer.echo(f"wrote {out}")


@app.command()
def incidents(
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    out: Path = typer.Option(
        Path("docs/incidents-report.md"), help="Where to write the report."
    ),
) -> None:
    """Incident artifact: detected spins/offs/near-stops + their mechanism."""
    from driverdna.db import Database
    from driverdna.incidents.report import build_incidents_report

    db_path = _require_store(db_path)
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


@app.command("lap-digest")
def lap_digest(
    out_dir: Path = typer.Option(..., "--out-dir", help="Where to write the slices."),
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    driver: str = typer.Option(None, help="Limit to one driver."),
    car: str = typer.Option(None, help="Limit to one car."),
    track: str = typer.Option(None, help="Limit to one track."),
    stride: int = typer.Option(6, help="Emit every Nth sample (60 Hz / N)."),
    margin: float = typer.Option(
        0.01, help="Widen each corner window by this lap fraction on both sides."
    ),
) -> None:
    """Readable per-corner slices of the raw trace (docs/LAP-ANALYSIS-PROTOCOL.md).

    Row selection and column selection only — the digest measures nothing.
    Self laps only; reference laps are never sliced.
    """
    from driverdna.analysis.digest import NoFrozenMap, build_digest
    from driverdna.db import Database

    db_path = _require_store(db_path)
    with Database.open(db_path) as db:
        try:
            report = build_digest(
                db, out_dir=out_dir, driver=driver, car=car, track=track,
                stride=stride, margin=margin,
            )
        except NoFrozenMap as exc:
            typer.secho(f"cannot build a digest: {exc}", fg="red", err=True)
            raise typer.Exit(2)

    for label in report.cohorts:
        typer.echo(f"  {label}")
    typer.echo(
        f"wrote {report.corners_written} corner slices "
        f"across {report.laps_written} lap(s) to {out_dir}"
    )
    # Never a silent hole in the evidence base.
    for name in report.unavailable_laps:
        typer.secho(f"  raw trace unavailable, not digested: {name}", fg="yellow")
    for note in report.skipped:
        typer.secho(f"  skipped {note}", fg="yellow")


@app.command("verify-observations")
def verify_observations_cmd(
    obs: Path = typer.Option(..., "--obs", help="Observations JSONL to check."),
    digest_dir: Path = typer.Option(
        ..., "--digest-dir", help="The digest those observations were read from."
    ),
    out: Path = typer.Option(None, "--out", help="Where to write the report."),
) -> None:
    """Check a lap reading's numbers against the trace it claims to read.

    Every quoted sample must equal the digest at the row it cites, and every
    numeral in the claim must be one of that observation's quoted samples.
    Exits 1 if anything is rejected, so a batch can be gated in a script.
    """
    from driverdna.analysis.verify import ObservationError, verify_observations

    try:
        report = verify_observations(obs, digest_dir)
    except ObservationError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2)

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.to_markdown())
        typer.echo(f"wrote {out}")
    for result in report.results:
        if not result.ok:
            typer.secho(f"  REJECTED {result.obs_id}", fg="red")
            for problem in result.problems:
                typer.echo(f"    - {problem}")
    typer.echo(f"{report.passed} grounded, {report.failed} rejected")
    if report.failed:
        raise typer.Exit(1)


@app.command("rebuild-map")
def rebuild_map(
    car: str = typer.Option(..., help="Car label of the cohort to rebuild."),
    track: str = typer.Option(..., help="Track label of the cohort to rebuild."),
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    driver: str = typer.Option("owner", help="Driver whose classes are re-derived."),
    allow_missing_traces: bool = typer.Option(
        False, "--allow-missing-traces",
        help="Proceed even when laps' raw traces are missing here but were "
             "never evicted here (they are intact on the machine that "
             "imported them). Their phase times are cleared. Only pass this "
             "if this machine is the one that matters.",
    ),
) -> None:
    """In-place refreeze of a cohort's frozen corner map from its full lap set.

    Recomputes each corner's centroid + canonical windows from every lap
    imported so far (not just the ones that first froze the map), re-measures
    phase times against the new windows, admits any genuinely new corners, and
    reclassifies. corner IDs never change, so evidence IDs stay valid. A lap
    whose raw blob was evicted past retention can't be re-measured — its stale
    phase times are cleared and reported, never left silently outdated.

    Refuses outright, changing nothing, when a lap's raw trace is merely
    absent on this machine rather than evicted from it: those measurements are
    still reproducible where the lap was imported, so destroying them here
    would be an unrecoverable loss blamed on retention (SPEC.md A26).
    """
    from driverdna.config import load_config
    from driverdna.db import Database
    from driverdna.pipeline import RawTracesUnavailable, rebuild_cohort_map

    db_path = _require_store(db_path)
    config = load_config()
    try:
        with Database.open(db_path) as db:
            result = rebuild_cohort_map(
                db, driver=driver, car=car, track=track, config=config,
                allow_missing_traces=allow_missing_traces,
            )
    except RawTracesUnavailable as e:
        shown = ", ".join(str(pk) for pk in e.lap_pks[:10])
        typer.echo(
            f"error: refusing to rebuild — {len(e.lap_pks)} lap(s) have no raw "
            f"trace on this machine and were not evicted here.\n"
            f"  lap_pk(s): {shown}{', ...' if len(e.lap_pks) > 10 else ''}\n"
            "  Raw traces live on local disk beside the machine that imported\n"
            "  the lap, so these are almost certainly intact there. Rebuilding\n"
            "  here would clear their phase times permanently.\n"
            "  Run rebuild-map on the machine holding those laps' blobs, or\n"
            "  pass --allow-missing-traces to clear them deliberately.\n"
            "  Nothing has been modified."
        )
        raise typer.Exit(code=2) from None
    if not result.existed:
        typer.echo(f"error: no corner map for {car} @ {track} — nothing to rebuild")
        raise typer.Exit(code=2)

    typer.echo(f"rebuilt {car} @ {track}")
    for c in result.corners:
        shift = "GPS-degraded" if c.centroid_shift_m is None else f"{c.centroid_shift_m:.1f} m"
        win = "window shifted" if c.window_changed else "window unchanged"
        line = (
            f"  {c.corner_id}: centroid {shift}, {win}, "
            f"{c.laps_remeasured} lap(s) re-measured"
        )
        if c.laps_cleared:
            line += (
                f", {len(c.laps_cleared)} cleared (no raw trace): {c.laps_cleared}"
            )
        typer.echo(line)
    if result.admitted:
        typer.echo(f"  admitted new corners: {', '.join(result.admitted)}")
    for corner_id, old, new in result.class_changes:
        typer.echo(f"  CLASS CHANGE {corner_id}: {old} -> {new}")
    if result.total_cleared:
        reason = (
            "were evicted past retention"
            if not allow_missing_traces
            else "are not readable on this machine (--allow-missing-traces)"
        )
        typer.echo(
            f"note: {result.total_cleared} phase-time record(s) cleared — their raw "
            f"traces {reason} and can't be re-measured against the "
            f"new windows. The laps' identity, metrics, and detectors are unchanged."
        )


@app.command("exclude-reference")
def exclude_reference_cmd(
    lap_pk: int = typer.Argument(
        ..., help="lap_pk of the reference lap to exclude (see the cohort "
                   "view's References panel, or GET /api/laps)."
    ),
    note: str = typer.Option(
        None, "--note", help="Optional note recorded with the exclusion."
    ),
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
) -> None:
    """Exclude a reference lap from the envelope and vs-reference findings.

    Reversible (`include-reference`) and audited (SPEC.md A39, R3 curation):
    the lap and its measurements are never deleted, only marked excluded —
    the reference envelope and every vs-reference finding recompute without
    it immediately, since both read live off the database on every call.
    """
    from datetime import UTC, datetime

    from driverdna.db import Database

    db_path = _require_store(db_path)
    with Database.open(db_path) as db:
        try:
            db.exclude_reference_lap(
                lap_pk=lap_pk, note=note, created_at=datetime.now(UTC).isoformat(),
            )
        except ValueError as e:
            typer.echo(f"error: {e}")
            raise typer.Exit(code=2) from None
    typer.echo(
        f"excluded lap_pk={lap_pk} — the reference envelope and vs-reference "
        "findings recompute without it; `include-reference` undoes this"
    )


@app.command("include-reference")
def include_reference_cmd(
    lap_pk: int = typer.Argument(..., help="lap_pk of the reference lap to re-include."),
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
) -> None:
    """Undo a reference-lap exclusion (never touches the lap or its
    measurements). Rejects a lap_pk that isn't currently excluded, rather
    than silently no-op-ing — same discipline as clearing an annotation
    that was never set."""
    from driverdna.db import Database

    db_path = _require_store(db_path)
    with Database.open(db_path) as db:
        if lap_pk not in db.reference_exclusions():
            typer.echo(f"error: lap_pk={lap_pk} is not currently excluded")
            raise typer.Exit(code=2)
        db.include_reference_lap(lap_pk)
    typer.echo(f"included lap_pk={lap_pk} — back in the envelope")


@app.command("store-copy")
def store_copy(
    source: str = typer.Option(..., "--from", help="Source store (path or URL)."),
    target: str = typer.Option(..., "--to", help="Target store (path or URL)."),
) -> None:
    """Copy a store's compact rows into another, in either direction.

    Primary keys are preserved exactly, because evidence IDs are those
    numbers — renumbering would invalidate every stored finding, annotation
    and citation. Raw lap blobs are not copied: they live on local disk, and
    a machine without them reports the raw trace as unavailable, the same
    state retention already produces.

    Refuses a non-empty target rather than merging. Prints a per-table
    checksum comparison; identical checksums are the proof the copy is
    faithful, and the one that catches a float truncated by a wrong column
    type at the row level rather than months later in a report.
    """
    from driverdna.db import Database
    from driverdna.migrate import compare, copy_store, repaired_int_columns
    from driverdna.store import describe

    src = _require_store(source)
    with Database.open(src) as source_db, Database.open(target) as target_db:
        try:
            counts = copy_store(source_db, target_db)
        except ValueError as e:
            typer.echo(f"error: {e}")
            raise typer.Exit(code=2) from None

        typer.echo(f"copied {describe(src)} -> {describe(target)}")
        for table, n in counts.items():
            if n:
                typer.echo(f"  {table}: {n}")

        for column, n in sorted(repaired_int_columns.items()):
            typer.echo(
                f"  repaired {n} value(s) in {column}: stored as a BLOB by an "
                "older build, written back as an integer"
            )

        differing = compare(source_db, target_db)

    if differing:
        typer.echo(f"MISMATCH in: {', '.join(differing)}")
        typer.echo("the copy is NOT faithful — do not cut over")
        raise typer.Exit(code=1)
    typer.echo(f"verified: all {len(counts)} tables checksum-identical")
    typer.echo("raw lap blobs are local and were not copied")


@app.command("migrate-blobs")
def migrate_blobs(
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    blob_root: Path = typer.Option(
        None, "--blobs",
        help="Where raw lap blobs live. Defaults to <db>.blobs/ (or DRIVERDNA_BLOB_ROOT).",
    ),
) -> None:
    """Move raw lap blobs out of the database and onto local disk.

    Raw samples used to be stored inside the database; they now live beside
    it. Opening an older database keeps reading them in place, so this is
    safe to defer — run it once to complete the move and reclaim the space.
    Idempotent: rows are removed only after their file exists.
    """
    from driverdna.db import Database

    db_path = _require_store(db_path)

    with Database.open(db_path, blob_root=blob_root) as db:
        moved = db.drain_legacy_blobs()

    if moved == 0:
        typer.echo("nothing to move — raw blobs already live on disk")
    else:
        store = blob_root or f"{db_path}.blobs"
        typer.echo(f"moved {moved} raw lap blob(s) to {store}")
        typer.echo("run `VACUUM` on the DB to reclaim the freed space")


@app.command("backfill-blobs")
def backfill_blobs_cmd(
    csv_dir: Path = typer.Option(
        ..., "--from",
        help="Directory of source CSVs to restore raw traces from (searched "
             "recursively). Each is matched to a lap by content fingerprint.",
    ),
    db_path: str = typer.Option(
        None, "--db",
        help="Store: a SQLite path, or a postgresql:// URL. "
             "Defaults to $DRIVERDNA_DATABASE_URL, else driverdna.db.",
    ),
    blob_root: Path = typer.Option(
        None, "--blobs",
        help="Where raw lap blobs live. Defaults to <db>.blobs/ (or DRIVERDNA_BLOB_ROOT).",
    ),
) -> None:
    """Restore missing raw lap blobs from their source CSVs, in place.

    The recovery path after a store move: `store-copy` carries every compact
    row but not raw blobs (they are per-machine), and re-importing the same
    CSVs is a no-op because the copied rows already dedup by content hash. This
    matches each CSV to a lap by that lap's own fingerprint and writes only the
    missing `<lap_pk>.npz` — never creating, deleting, or renumbering a lap
    row, so evidence IDs stay valid. Idempotent and safe to re-run.
    """
    from driverdna.db import Database
    from driverdna.pipeline import backfill_blobs

    db_path = _require_store(db_path)
    with Database.open(db_path, blob_root=blob_root) as db:
        result = backfill_blobs(db, csv_dir)

    typer.echo(f"restored {len(result.restored)} raw lap blob(s)")
    if result.unmatched_laps:
        typer.echo(
            f"  {len(result.unmatched_laps)} lap(s) still without a raw trace — "
            "no matching CSV found"
        )
    if result.unmatched_csvs:
        typer.echo(
            f"  {len(result.unmatched_csvs)} CSV(s) matched no lap needing a "
            "trace (already present here, or not from this store)"
        )
    if result.unparseable:
        typer.echo(f"  {len(result.unparseable)} file(s) could not be parsed")


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
