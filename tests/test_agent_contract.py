"""Guards the multi-agent contract: the rules files three different tools read.

Claude Code, Gemini CLI and Antigravity all work on this repository, and each
discovers its instructions differently. Nothing about that wiring is exercised
by the rest of the suite — a broken `.gemini/settings.json` or a rules file that
quietly outgrew Antigravity's size cap fails *silently*, by the agent simply
never seeing the rules. These tests make that failure loud.

Deliberately narrow. The project's actual invariants (determinism, the source
contract, taxonomy, reference-lap isolation, Postgres hardening) are covered by
the rest of the suite; this file only guards the layer those tests cannot see.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

AGENTS = ROOT / "AGENTS.md"
ANTIGRAVITY_RULE = ROOT / ".agents" / "rules" / "driverdna.md"
GEMINI_SETTINGS = ROOT / ".gemini" / "settings.json"
CLAUDE = ROOT / "CLAUDE.md"

# Antigravity refuses to load a rules or workflow file longer than this.
# Exceeding it does not warn — the rules just do not reach the agent.
ANTIGRAVITY_CHAR_LIMIT = 12_000

# The budget tested against, deliberately below the real cliff. Crossing 12,000
# fails silently in the tool, so the guard has to fire while there is still room
# to fix it rather than at the moment the rules stop loading.
RULE_FILE_BUDGET = 11_000

_BLOCK = re.compile(
    r"<!-- shared:non-negotiables -->\n(.*?)\n<!-- /shared:non-negotiables -->",
    re.DOTALL,
)


def _shared_block(path: Path) -> str:
    """The non-negotiables text between the shared-block markers."""
    match = _BLOCK.search(path.read_text(encoding="utf-8"))
    assert match, f"{path.name} is missing the shared:non-negotiables markers"
    return match.group(1)


def test_agents_md_fits_antigravity_rule_limit():
    """AGENTS.md is the portable source of the rules, so it has to fit in the
    strictest reader. CLAUDE.md (~26k) does not, which is why the rules were
    extracted here in the first place — this test stops AGENTS.md from drifting
    back over the same cliff."""
    assert AGENTS.exists(), "AGENTS.md is the single source of the build rules"
    length = len(AGENTS.read_text(encoding="utf-8"))
    assert length < RULE_FILE_BUDGET, (
        f"AGENTS.md is {length} chars, over the {RULE_FILE_BUDGET} budget "
        f"(Antigravity's real cliff is {ANTIGRAVITY_CHAR_LIMIT}, where it stops "
        "loading the file without saying so). Move detail into docs/ and "
        "reference it instead."
    )


def test_antigravity_rule_exists_and_fits_the_limit():
    assert ANTIGRAVITY_RULE.exists(), (
        "Antigravity reads workspace rules from .agents/rules/; without this "
        "file it works on the project with no instructions at all"
    )
    length = len(ANTIGRAVITY_RULE.read_text(encoding="utf-8"))
    assert length < RULE_FILE_BUDGET, (
        f".agents/rules/driverdna.md is {length} chars, over the "
        f"{RULE_FILE_BUDGET} budget (Antigravity's real cliff is "
        f"{ANTIGRAVITY_CHAR_LIMIT})"
    )


def test_non_negotiables_do_not_drift_between_the_two_rule_files():
    """The one deliberate duplication in the repo.

    Antigravity's own docs do not promise that a root AGENTS.md is loaded, and
    its @-references resolve relative to the rule file, so the hardest rules are
    mirrored into .agents/rules/driverdna.md to land unconditionally. Mirrored
    content rots, so it is pinned — the same reasoning as
    test_report.py::test_report_css_tokens_match_ui_tokens_json.
    """
    assert _shared_block(AGENTS) == _shared_block(ANTIGRAVITY_RULE), (
        "The non-negotiables in .agents/rules/driverdna.md have drifted from "
        "AGENTS.md. Edit AGENTS.md, then copy the block across."
    )


def test_gemini_cli_is_pointed_at_agents_md():
    """Gemini CLI loads GEMINI.md by default and would find nothing here. The
    settings file redirects it at the shared rules; if this drifts, Gemini works
    on the project with no context."""
    assert GEMINI_SETTINGS.exists(), ".gemini/settings.json is how Gemini CLI finds the rules"
    settings = json.loads(GEMINI_SETTINGS.read_text(encoding="utf-8"))
    context_files = settings.get("context", {}).get("fileName", [])
    assert "AGENTS.md" in context_files, (
        f"context.fileName is {context_files!r}; it must include AGENTS.md or "
        "Gemini CLI loads no project rules"
    )


def test_the_non_negotiables_still_say_the_non_negotiable_things():
    """Drift is not the only failure mode. An agent tidying prose could delete a
    rule from *both* copies and leave test_non_negotiables_do_not_drift green.
    These anchors are the load-bearing clauses; removing one should require
    deliberately editing this test, which is the point."""
    # Whitespace-collapsed so re-wrapping a paragraph is not a failure; only
    # actually removing the clause is.
    block = " ".join(_shared_block(AGENTS).split())
    for anchor in (
        "never produces or adjusts a number",
        '"Insufficient data" over guessing',
        "Reference laps never enter self history",
        "env-only",
        "ConfigStore",
        "quality-flagged",
        "never computes a measurement",
    ):
        assert anchor in block, f"a non-negotiable went missing: {anchor!r}"


def test_gitignore_keeps_the_agent_rule_files_tracked():
    """The rule files are useless if they never reach the repository. A bare
    `.gemini/` or `.agents/` line would untrack the guardrails every non-Claude
    agent depends on, and nothing else would notice."""
    lines = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    }
    for bad in (".gemini/", ".agents/", ".agent/", "AGENTS.md", "GEMINI.md"):
        assert bad not in lines, (
            f".gitignore has a bare `{bad}` rule, which untracks the agent "
            "contract. Ignore the tool's scratch, not its rules."
        )
    assert "!.gemini/settings.json" in lines


def test_gemini_assistant_action_is_pinned_to_a_version_that_exists():
    """`run-gemini-cli` is pre-1.0 and has no `v1` tag. The original `@v1` pin
    here made the workflow fail on every run with "Unable to resolve action",
    which is why the bot never answered issue #4. Cheap regression guard."""
    workflow = (ROOT / ".github" / "workflows" / "gemini-assistant.yml").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"run-gemini-cli@v[1-9]\d*(?![\d.])", workflow), (
        "run-gemini-cli is pinned to a major tag that does not exist; the "
        "action is still on v0.x"
    )
    assert re.search(r"run-gemini-cli@(v0[\w.]*|[0-9a-f]{40})", workflow), (
        "pin run-gemini-cli to an exact v0.x release or a commit SHA"
    )
    assert "github.repository_owner" in workflow, (
        "the assistant job holds `contents: write` and is driven by issue-comment "
        "text; keep it gated on the repository owner"
    )


def test_gitleaks_version_is_pinned_and_checksummed():
    """The secrets job downloads a raw gitleaks release binary rather than
    using gitleaks-action, so nothing here trusts a third-party Action's own
    supply chain (same reasoning as pinning run-gemini-cli by exact version
    above) — but that only holds if the version and checksum are pinned, not
    left to float. Deliberately does not fetch the real checksum over the
    network to verify it (the suite has to stay runnable offline); this is a
    format guard, not a live one."""
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )
    version_match = re.search(r'GITLEAKS_VERSION:\s*"(\d+\.\d+\.\d+)"', workflow)
    assert version_match, "gitleaks version must be pinned to an exact release"
    sha_match = re.search(r'GITLEAKS_SHA256:\s*"([0-9a-f]{64})"', workflow)
    assert sha_match, (
        "gitleaks download must be checksummed with a 64-hex-char SHA256, "
        "verified against the download in the same step (sha256sum -c)"
    )
    assert "sha256sum -c" in workflow, (
        "the pinned checksum must actually be verified against the download, "
        "not just declared"
    )


def test_claude_md_imports_agents_md_without_restating_it():
    """One copy of the rules, no drift. CLAUDE.md pulls AGENTS.md in via the
    @path import rather than repeating it."""
    claude = CLAUDE.read_text(encoding="utf-8")
    assert "@AGENTS.md" in claude, (
        "CLAUDE.md must import @AGENTS.md so Claude Code loads the shared rules"
    )
    assert "<!-- shared:non-negotiables -->" not in claude, (
        "CLAUDE.md restates the non-negotiables block. Reference AGENTS.md "
        "instead — a third copy is a third thing to drift."
    )
