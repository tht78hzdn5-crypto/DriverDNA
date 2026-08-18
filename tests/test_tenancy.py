"""The route-enumerated cross-tenant gate.

`docs/ACCOUNTS-SPEC.md:150-157` specified this file and BUG-036 filed
its absence: "seed two users with overlapping car/track, then enumerate
every read endpoint and assert user A never sees a row, a count, an
evidence ID or a corner map belonging to user B." Route enumeration is
the point — a hand-written endpoint list will miss one, per DEPLOY-SPEC's
own H1 reasoning, and BUG-032 shipped in the first place because
`/api/config/history` had been overlooked.

**Enumeration mechanism** (same shape as `test_auth_api.py:66`
`_concrete_api_routes`): walk `app.routes`, classify every non-public
`/api/*` route into exactly one bucket, and fail if a route is
unclassified. That single failure — "route X exists but this file does
not test it" — is the future-proofing this gate was written for. A
future endpoint has to be classified before it can ship.

**Buckets**:
- `TENANT_SCOPED_READS` — user B's request must return an empty result,
  a 404, or otherwise none of A's data.
- `WRITES_INDIRECTLY_TESTED` — write endpoints whose cross-tenant
  behaviour is already pinned by focused tests. Named here (with the
  test files) so the enumeration knows they are covered.
- `INSTANCE_WIDE_TODAY` — endpoints whose current design is not tenant-
  scoped (e.g. `/api/config` under the BUG-032b design gap). Same
  response for A and B is not a leak: it is the specified behaviour.
  When BUG-032b lands, these move to `TENANT_SCOPED_READS`.

Anything auth-related is already excluded via `PUBLIC_API_PATHS` in
`ui/api.py` — this file honours that set.

**What this gate does not do**: cover write endpoints via new tests here.
The four cross-tenant defects filed by A53 (BUG-031 through BUG-034) all
land with their own pinning tests; enumerating them here would duplicate,
not add. `WRITES_INDIRECTLY_TESTED` names those tests explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.db import Database
from driverdna.report.payload import cohort_slug
from driverdna.ui.api import PUBLIC_API_PATHS, create_app
from driverdna.ui.auth import hash_password


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SECRET = "tenancy-gate-secret-passphrase-must-be-long-enough"
BETA_EMAIL, BETA_PASSWORD = "beta@example.com", "beta-not-owner-password"

# The fixture cohort — imported by the CLI-as-owner (`user_pk=1`) fixture.
SPA_SLUG = cohort_slug("GR86", "Spa-Francorchamps")

# --- Route classification ------------------------------------------------
#
# Every non-public /api/* route lives in exactly one bucket. New routes
# fail the enumeration test until they are classified. The enumeration is
# ordered (method, path), so a change to one line is visible.
#
# Placeholder substitution: `{slug}` is filled with an existing owner
# cohort (so a leak is detectable), `{corner_id}` with a corner that
# exists in the fixture, other params with a stub value likely to be
# resolvable if the endpoint were leaking. If your assertion is "returns
# empty" the stub value is often irrelevant; if it is "returns 404"
# picking a value the OWNER would resolve to real data hardens the test.

FIXTURE_CORNER_ID = "C01"


def _url(path: str) -> str:
    """Substitute concrete values into a declared path."""
    return (
        path
        .replace("{slug}", SPA_SLUG)
        .replace("{corner_id}", FIXTURE_CORNER_ID)
        .replace("{metric}", "corner_entry_v_kmh")
        .replace("{lap_pk}", "1")
        .replace("{change_pk}", "1")
        .replace("{finding_id}", "vs-self:GR86:Spa-Francorchamps:C01:mid:opportunity")
        .replace("{session_id}", "deadbeefcafe")
        .replace("{index}", "0")
    )


#: Reads that MUST scope to the calling user.
#:   ("GET", "/api/cohorts"): {"assert": "empty_list"|"not_found"|"empty_dict_of_lists",
#:                             "cohort_query": bool}
TENANT_SCOPED_READS: dict[tuple[str, str], dict[str, Any]] = {
    # /api/cohorts returns a list of cohort dicts. Bob has none.
    ("GET", "/api/cohorts"): {"assert": "empty_list"},

    # Per-cohort payloads: the slug resolves against the OWNER's cohorts,
    # so Bob asking for it must 404 rather than return the payload.
    ("GET", "/api/cohorts/{slug}/payload"): {"assert": "not_found"},
    ("GET", "/api/cohorts/{slug}/corners"): {"assert": "not_found"},
    ("GET", "/api/cohorts/{slug}/corners/{corner_id}/reference-phases"): {
        "assert": "not_found",
    },
    ("GET", "/api/cohorts/{slug}/track-trace"): {"assert": "not_found"},

    # /api/laps takes a ?cohort=slug parameter. Bob's request must 404
    # (slug doesn't resolve for him) rather than return the lap list.
    ("GET", "/api/laps"): {"assert": "not_found", "query": "?cohort=" + SPA_SLUG},

    # Per-corner metric distributions — same rationale.
    ("GET", "/api/metrics/{corner_id}/{metric}/distribution"): {
        "assert": "not_found",
        "query": "?cohort=" + SPA_SLUG,
    },

    # /api/driver/summary returns counts (laps, cohorts). Bob's counts
    # must be zero.
    ("GET", "/api/driver/summary"): {"assert": "empty_summary"},

    # /api/driver is SSE — the terminal `complete` event's payload must
    # carry Bob's empty rollup, not the owner's.
    ("GET", "/api/driver"): {"assert": "empty_sse_payload"},

    # /api/driver/score-history returns a list of points. Bob has none.
    ("GET", "/api/driver/score-history"): {"assert": "empty_or_no_history"},

    # /api/config/history — fixed by BUG-032a; re-pinned here as part of
    # the enumeration so it stays green through future refactors.
    ("GET", "/api/config/history"): {"assert": "empty_list"},

    # /api/settings/ai-key — Bob has never set a key; reports so.
    ("GET", "/api/settings/ai-key"): {
        "assert": "not_configured", "query": "?provider=gemini",
    },

    # /api/garage61/status — fixed by BUG-033; re-pinned. Bob is not
    # connected; the env fallback must not report him as connected.
    ("GET", "/api/garage61/status"): {"assert": "not_connected"},
}

#: Writes whose cross-tenant behaviour is proven elsewhere. Named so a
#: reader can go read that pinning test; the enumeration test asserts
#: these route strings exist as declared today.
WRITES_INDIRECTLY_TESTED: dict[tuple[str, str], str] = {
    ("POST", "/api/laps/upload"):
        "tests/test_upload_api.py: upload owner-scoped from request session",
    ("POST", "/api/findings/{finding_id}/annotate"):
        "tests/test_finding_annotations_tenancy.py (BUG-031)",
    ("DELETE", "/api/findings/{finding_id}/annotate"):
        "tests/test_finding_annotations_tenancy.py (BUG-031)",
    ("POST", "/api/laps/{lap_pk}/exclude"):
        "tests/test_reference_curation.py: validates lap ownership before excluding",
    ("DELETE", "/api/laps/{lap_pk}/exclude"):
        "tests/test_reference_curation.py: 404 for laps not in this user's exclusions",
    ("POST", "/api/config/propose"):
        "no cross-tenant surface — a proposal is stateless (no history row)",
    ("POST", "/api/config/apply"):
        "tests/test_config_tenancy.py (BUG-032a): applies to this user's row only",
    ("POST", "/api/config/revert/{change_pk}"):
        "tests/test_config_tenancy.py (BUG-032a): another user's pk 404s",
    ("PUT", "/api/settings/ai-key"):
        "tests/test_byok_api.py: keys keyed on (owner_user_pk, provider)",
    ("DELETE", "/api/settings/ai-key"):
        "tests/test_byok_api.py: deletes only this user's row",
    ("POST", "/api/sync"):
        "tests/test_cockpit_api.py (BUG-033): env-token fallback closed under auth",
    ("DELETE", "/api/garage61/disconnect"):
        "deletes WHERE owner_user_pk=? (ui/api.py:1806); byok pattern",
    ("POST", "/api/cohorts/{slug}/rebuild-map"):
        "cohort resolver is owner-scoped (test_cockpit_api.py rebuild tests)",
    ("POST", "/api/chat/sessions"):
        "creates a session with request.user_pk (chat pattern)",
    ("POST", "/api/chat/sessions/{session_id}/messages"):
        "e196c2d BUG-037: session ID lookup checks ownership",
    ("POST", "/api/chat/sessions/{session_id}/confirm/{index}"):
        "e196c2d BUG-037: same session ownership check",
    ("POST", "/api/auth/logout"):
        "clears the caller's session cookie only — no DB access, no data surface",
}

#: Endpoints whose current design is deliberately not tenant-scoped —
#: same response to every user, and that IS the specification today.
#: When BUG-032b lands, `/api/config` moves out of this bucket.
INSTANCE_WIDE_TODAY: dict[tuple[str, str], str] = {
    ("GET", "/api/config"):
        "instance-wide config (BUG-032b tracks the per-user redesign)",
    ("GET", "/api/explain"):
        "static methodology text — user-independent by design",
}


# --- Fixture --------------------------------------------------------------


@pytest.fixture(scope="module")
def owner_seeded_db(tmp_path_factory):
    """CLI import populates the DB under `owner_user_pk=1` (the CLI's
    default). This gives us the "user A" — cohorts, laps, corner maps,
    config history via a synthetic apply, and an annotation seeded via
    the DB layer. User B (the beta user) is separately registered."""
    root = tmp_path_factory.mktemp("tenancy")
    db_path = root / "tenancy.db"
    result = CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output

    # Give owner (user_pk=1) a real password so we can log them in too if
    # a test needs a positive control. Migration seeds a placeholder hash
    # that verify_password can never match.
    with Database.open(db_path) as db:
        with db.conn:
            db.conn.execute(
                "UPDATE users SET password_hash=? WHERE user_pk=1",
                (hash_password("owner-password"),),
            )
            # Register user_pk=2 as the "beta user" directly, so tests
            # can log in without going through the HTTP registration path.
            db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (BETA_EMAIL, hash_password(BETA_PASSWORD)),
            )
    return {"db_path": db_path, "root": root}


@pytest.fixture
def beta_client(owner_seeded_db, tmp_path):
    """A TestClient signed in as the beta user (`user_pk=2`), against a
    DB where user 1 has a full fixture cohort. Every read this client
    makes should see nothing of user 1's data."""
    config_path = tmp_path / "cfg.toml"
    app = create_app(
        owner_seeded_db["db_path"], config_path, session_secret=SECRET,
    )
    c = TestClient(app)
    r = c.post("/api/auth/login",
               json={"email": BETA_EMAIL, "password": BETA_PASSWORD})
    assert r.status_code == 200, r.text
    return c


# --- The enumeration gate ------------------------------------------------


def _concrete_api_routes(app) -> list[tuple[str, str, str]]:
    """Every `/api/*` route the app declares, as
    `(method, declared_path, concrete_url)`. Same shape
    `test_auth_api.py::_concrete_api_routes` uses — copied deliberately,
    since these two enumerations answer different questions from the same
    source of truth (all routes) and diverging would let one file miss
    an endpoint the other caught. If the two shapes drift, promote to a
    shared helper."""
    seen: list[tuple[str, str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            seen.append((method, path, _url(path)))
    assert seen, "no /api routes discovered — the enumeration itself is broken"
    return seen


def test_every_api_route_is_classified_for_tenancy(beta_client):
    """The enumeration itself. Any /api route not accounted for in one of
    the three buckets — read (must not leak), write (proven elsewhere),
    or instance-wide (specified as user-independent) — fails this test.

    A new endpoint has to be classified before it can ship. That is the
    point of route enumeration, and the reason the missing gate let
    BUG-031/BUG-032/BUG-033 all reach `main` unnoticed."""
    unclassified = []
    for method, declared, _ in _concrete_api_routes(beta_client.app):
        if declared in PUBLIC_API_PATHS:
            continue
        key = (method, declared)
        buckets = (
            "TENANT_SCOPED_READS" if key in TENANT_SCOPED_READS
            else "WRITES_INDIRECTLY_TESTED" if key in WRITES_INDIRECTLY_TESTED
            else "INSTANCE_WIDE_TODAY" if key in INSTANCE_WIDE_TODAY
            else None
        )
        if buckets is None:
            unclassified.append(f"{method} {declared}")
    assert not unclassified, (
        "these /api routes are not classified for tenancy — add each to "
        "TENANT_SCOPED_READS, WRITES_INDIRECTLY_TESTED, or "
        "INSTANCE_WIDE_TODAY at the top of this file:\n  "
        + "\n  ".join(sorted(unclassified))
    )


def test_public_endpoints_stay_in_public_paths():
    """PUBLIC_API_PATHS is the auth guard's own bypass list. If a new
    non-public path sneaks in here, the guard is silently loosened for
    it. This is a low-effort belt-and-braces check — DEPLOY-SPEC's H1
    done-criterion in test_auth_api.py is the primary guard."""
    assert PUBLIC_API_PATHS, "PUBLIC_API_PATHS is empty — auth guard is nothing"
    for p in PUBLIC_API_PATHS:
        assert p.startswith("/api/") or p == "/health", (
            f"unexpected path in PUBLIC_API_PATHS: {p!r}"
        )


# --- Per-endpoint leak assertions ---------------------------------------
#
# One test per tenant-scoped read, keyed on the (method, declared) pair,
# so a route sees exactly the assertion it was classified with. Testing
# through pytest.mark.parametrize keeps failures per-route instead of
# stopping at the first leak.


@pytest.mark.parametrize(
    "route", sorted(TENANT_SCOPED_READS.keys()),
    ids=lambda r: f"{r[0]} {r[1]}",
)
def test_beta_user_sees_none_of_owners_data(beta_client, route):
    """The core BUG-036 gate. Owner (user_pk=1) has the full fixture
    cohort seeded; beta (user_pk=2) just registered. Every read must
    return Bob's own empty world, not user 1's rows.

    Uses the OWNER's real slug in the URL — that is exactly the leak
    shape a bug would take (attacker knows or guesses the cohort key).
    """
    method, declared = route
    spec = TENANT_SCOPED_READS[route]
    url = _url(declared) + spec.get("query", "")

    r = beta_client.request(method, url)

    kind = spec["assert"]
    if kind == "empty_list":
        assert r.status_code == 200, r.text
        assert r.json() == [], (
            f"{method} {url} leaked {len(r.json())} rows of user 1's data: "
            f"{r.json()[:2]!r}"
        )
    elif kind == "not_found":
        assert r.status_code == 404, (
            f"{method} {url} should 404 for the beta user (slug/id "
            f"resolves against user 1); got {r.status_code} {r.text[:200]}"
        )
    elif kind == "empty_summary":
        assert r.status_code == 200, r.text
        body = r.json()
        # /api/driver/summary returns headline counts. All must be zero.
        for k, v in body.items():
            if isinstance(v, int):
                assert v == 0, (
                    f"/api/driver/summary key {k!r} = {v!r} for beta user; "
                    f"leaks user 1's data. Full body: {body!r}"
                )
    elif kind == "empty_sse_payload":
        assert r.status_code == 200, r.text
        # /api/driver streams SSE ending in a `complete` event whose
        # payload holds the driver rollup. Beta has no laps → the
        # payload's cohort count must be 0.
        events = _parse_sse_events(r.text)
        complete = [e for e in events if e.get("type") == "complete"]
        assert complete, f"no `complete` event in SSE: {events!r}"
        payload = complete[0].get("payload") or complete[0]
        cohorts = payload.get("cohorts") if isinstance(payload, dict) else None
        assert cohorts is None or cohorts == [], (
            f"/api/driver SSE payload for beta carried {len(cohorts or [])} "
            f"cohorts of user 1's data"
        )
    elif kind == "empty_or_no_history":
        # SSE too — `complete` event's `history` (or top-level) is
        # either absent or empty.
        assert r.status_code == 200, r.text
        events = _parse_sse_events(r.text)
        complete = [e for e in events if e.get("type") == "complete"]
        for ev in complete:
            payload = ev.get("payload") or ev
            history = payload.get("history") if isinstance(payload, dict) else None
            if history:
                pytest.fail(
                    f"/api/driver/score-history leaked {len(history)} "
                    f"points of user 1's history to beta"
                )
    elif kind == "not_configured":
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("configured") is False, (
            f"beta shows an AI key as configured: {body!r}"
        )
    elif kind == "not_connected":
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("connected") is False, (
            f"beta shows Garage61 as connected: {body!r}"
        )
    else:
        pytest.fail(f"unknown assertion kind {kind!r} in the classifier")


def _parse_sse_events(text: str) -> list[dict]:
    """Extract SSE data-frames as dicts. Cribbed from other test files
    to keep this one self-contained (no cross-test imports)."""
    import json
    events: list[dict] = []
    for frame in text.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        for line in frame.split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[len("data: "):]))
                except json.JSONDecodeError:
                    pass  # keepalives/comments are not JSON
    return events


# --- Direct leak proof: user 1's slug is real, and beta doesn't see it --


def test_owner_data_is_actually_seeded(owner_seeded_db):
    """Sanity: without this the 'not_found' assertions above would pass
    vacuously — Beta getting 404 on a cohort that doesn't exist for
    ANYONE is not evidence of isolation. Assert directly that user 1
    holds real rows in the fixture cohort."""
    with Database.open(owner_seeded_db["db_path"]) as db:
        n_laps = db.conn.execute(
            "SELECT COUNT(*) AS n FROM laps "
            "WHERE owner_user_pk=1 AND car=? AND track=?",
            ("GR86", "Spa-Francorchamps"),
        ).fetchone()["n"]
        assert n_laps > 0, (
            "owner_seeded_db fixture broken: user 1 has no GR86/Spa laps"
        )
        # And that beta has a user row but zero laps.
        beta_pk = db.conn.execute(
            "SELECT user_pk FROM users WHERE email=?", (BETA_EMAIL,),
        ).fetchone()["user_pk"]
        assert beta_pk == 2
        n_beta = db.conn.execute(
            "SELECT COUNT(*) AS n FROM laps WHERE owner_user_pk=?", (beta_pk,),
        ).fetchone()["n"]
        assert n_beta == 0


# --- Regression pin: owner still sees own data through the same app -----


def test_owner_still_sees_their_own_data_positive_control(owner_seeded_db, tmp_path):
    """Guard against a fix that "closes the leak" by returning empty to
    everyone. Owner must still see their own cohorts through the same
    app configuration. Uses the same secret + a fresh app so the beta
    fixture's TestClient state doesn't bleed in."""
    app = create_app(
        owner_seeded_db["db_path"], tmp_path / "cfg.toml",
        session_secret=SECRET,
    )
    c = TestClient(app)
    r = c.post("/api/auth/login",
               json={"email": "owner@example.com", "password": "owner-password"})
    assert r.status_code == 200, r.text

    r = c.get("/api/cohorts")
    assert r.status_code == 200 and r.json(), (
        "owner sees no cohorts through the same app — the tenancy fix "
        "went too far and closed the read for everyone"
    )
    r = c.get(f"/api/cohorts/{SPA_SLUG}/payload")
    assert r.status_code == 200, r.text
