"""CoachChat: grounded conversation over the deterministic findings (M5).

The bundle is assembled deterministically; the model works through the
read-only tool surface; every response is mechanically validated before it
is shown: cited IDs must exist in the bundle, and any number-with-unit must
come from the bundle or a tool result of this turn. A rejected response is
regenerated once with the violations spelled out, then surfaced as an error
rather than shown. Config changes only stage here; applying them is the
driver's explicit act. Every turn is persisted with the bundle version,
evidence cited, and effects — the chat is auditable to the same standard as
the reports.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from driverdna.chat.tools import TOOL_DEFS, execute_tool
from driverdna.coach.grounding import number_pool, numeric_claims, unsupported_claims
from driverdna.coaching.ontology import PRINCIPLES
from driverdna.config import ConfigStore, DriverDNAConfig, config_snapshot
from driverdna.db import Database
from driverdna.model.taxonomy import SignalStatus
from driverdna.report.payload import build_cohort_payload, to_normalized_json

CHAT_PROMPT_VERSION = "chat-v2"

CHAT_SYSTEM_PROMPT = """\
You are DriverDNA's coaching chat. The attached bundle holds every
measurement that exists; the tools return live values from the same store.
Hard rules:
- Never invent a measurement. Any number with a unit must come from the
  bundle or a tool result in this turn. Cite finding IDs or obs:<n> refs
  for measured claims.
- "Insufficient data" and "not measured" are correct answers (e.g. tire
  slip has no channel and is never inferred). Say so plainly.
- Anything beyond the measurements is a hypothesis: label it as your
  interpretation with its basis. Racing canon may explain a finding but is
  never a measurement of this driver.
- Coaching: cite coaching_principle_id values (cp.<technique>.<name>) only
  from bundle.report.coaching (headline, secondary, self_checks) — never
  invent one, never promote one that isn't listed there. Commit to phrasing
  on measured ground; stay tentative on proxy ground; on a no_signal
  principle (self_check present), offer it as a labeled hypothesis and
  NEVER attach a confidence value or percentage to it, at any level.
- You may annotate a finding (acknowledged/intentional) only when the
  driver clearly asks; annotation suppresses framing, never deletes data.
- Config changes are only ever STAGED via propose_config_change; the driver
  applies them with an explicit /confirm. Never claim a change is active
  until then.
- Stay on this driver's data, the tool's methods, and the principles behind
  them. Decline car setups (no setup data) and off-topic requests.
- On disagreement, explain how the number was derived and offer the
  annotate/retune paths — don't simply concede or insist.
"""

_ID_TOKEN = re.compile(
    r"\b(?:obs:\d+|(?:vs-self|vs-principle|vs-reference):[A-Za-z0-9_:.\-]+"
    r"|cp\.[A-Za-z_]+\.[A-Za-z_]+)"
)


class ChatProvider(Protocol):
    def chat_step(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """One model step: {"text": str | None, "tool_calls": [{"id", "name", "args"}]}."""
        ...


class ClaudeChatProvider:
    def __init__(self, model: str, max_tokens: int = 4000):
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Chat requires it (env only; "
                "never persisted or logged). Tests use the mocked provider."
            )
        import anthropic

        self._client = anthropic.Anthropic()
        self._model = model
        self._max_tokens = max_tokens

    def chat_step(self, system, messages, tools):
        response = self._client.messages.create(
            model=self._model, max_tokens=self._max_tokens, system=system,
            messages=messages, tools=tools,
        )
        text_parts, tool_calls = [], []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name,
                                   "args": dict(block.input)})
        return {"text": "".join(text_parts) or None, "tool_calls": tool_calls,
                "raw_content": response.content}


def build_chat_bundle(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig
) -> dict[str, Any]:
    """Deterministic context bundle — a known, inspectable state."""
    report = build_cohort_payload(db, driver=driver, car=car, track=track, config=config)
    coach_runs = db.coach_history(driver=driver, car=car, track=track)
    return {
        "prompt_version": CHAT_PROMPT_VERSION,
        "bundle_version": report["payload_version"],
        "report": report,
        "annotations": db.annotations(),
        "config": {k: v for k, v in sorted(config_snapshot(config).items())},
        "latest_coach_plan": coach_runs[-1] if coach_runs else None,
    }


class GroundingError(RuntimeError):
    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("; ".join(violations))


class ChatSession:
    MAX_TOOL_STEPS = 8

    def __init__(
        self, *, db: Database, store: ConfigStore, provider: ChatProvider,
        driver: str, car: str, track: str, config: DriverDNAConfig,
        session_id: str,
    ):
        self.db = db
        self.store = store
        self.provider = provider
        self.config = config
        self.cohort = {"driver": driver, "car": car, "track": track}
        self.session_id = session_id
        self.bundle = build_chat_bundle(db, driver=driver, car=car, track=track, config=config)
        self.staged: list[dict[str, Any]] = []
        self._messages: list[dict[str, Any]] = [{
            "role": "user",
            "content": "CONTEXT BUNDLE (deterministic):\n"
                       + to_normalized_json(self.bundle),
        }]
        self._known_ids = {f["finding_id"] for f in self.bundle["report"]["findings"]}
        for f in self.bundle["report"]["findings"]:
            self._known_ids.update(f["evidence_ids"])
        coaching = self.bundle["report"]["coaching"]
        self._coaching_candidates = (
            ([coaching["headline"]] if coaching["headline"] else [])
            + coaching["secondary"] + coaching["self_checks"]
        )
        for c in self._coaching_candidates:
            self._known_ids.add(c["coaching_principle_id"])
            self._known_ids.update(c["evidence_ids"])

    # -- one driver turn ----------------------------------------------------

    def ask(self, text: str) -> dict[str, Any]:
        self.db.add_chat_turn(
            session_id=self.session_id,
            bundle_version=self.bundle["bundle_version"],
            role="driver", content=text,
        )
        self._messages.append({"role": "user", "content": text})
        try:
            reply, cited, effects = self._grounded_reply()
        except GroundingError as e:
            error_text = (
                "response rejected by the grounding contract (after one "
                f"regeneration): {'; '.join(e.violations)}"
            )
            self.db.add_chat_turn(
                session_id=self.session_id,
                bundle_version=self.bundle["bundle_version"],
                role="system-event", content=error_text,
            )
            return {"error": error_text}
        self.db.add_chat_turn(
            session_id=self.session_id,
            bundle_version=self.bundle["bundle_version"],
            role="assistant", content=reply,
            evidence_cited=sorted(cited), effects=effects,
        )
        return {"text": reply, "evidence": sorted(cited), "effects": effects,
                "staged": list(self.staged)}

    def _grounded_reply(self) -> tuple[str, set[str], dict[str, Any]]:
        for attempt in (1, 2):
            text, tool_pool, effects = self._drive_provider()
            violations = self._validate(text, tool_pool)
            if not violations:
                return text, set(_ID_TOKEN.findall(text)), effects
            if attempt == 1:
                self._messages.append({
                    "role": "user",
                    "content": "GROUNDING VIOLATIONS — regenerate, citing only "
                               "IDs from the bundle and numbers from the bundle "
                               f"or tool results: {'; '.join(violations)}",
                })
        raise GroundingError(violations)

    def _drive_provider(self) -> tuple[str, set[float], dict[str, Any]]:
        tool_pool: set[float] = set()
        effects: dict[str, Any] = {}
        for _ in range(self.MAX_TOOL_STEPS):
            step = self.provider.chat_step(
                CHAT_SYSTEM_PROMPT, self._messages, TOOL_DEFS
            )
            if not step["tool_calls"]:
                text = step["text"] or ""
                self._messages.append({"role": "assistant", "content": text})
                return text, tool_pool, effects
            # Record the assistant tool request and answer each call.
            self._messages.append({
                "role": "assistant",
                "content": step.get("raw_content") or json.dumps(step["tool_calls"]),
            })
            results = []
            for call in step["tool_calls"]:
                result = execute_tool(
                    db=self.db, store=self.store, cohort=self.cohort,
                    bundle=self.bundle, staged=self.staged,
                    name=call["name"], args=call["args"],
                )
                number_pool(result, tool_pool)
                if call["name"] == "annotate_finding" and "annotated" in result:
                    effects.setdefault("annotations", []).append(result["annotated"])
                if call["name"] == "propose_config_change" and "staged" in result:
                    effects.setdefault("staged_proposals", []).append(
                        result["staged"]["key"]
                    )
                results.append({
                    "type": "tool_result", "tool_use_id": call["id"],
                    "content": json.dumps(result, sort_keys=True),
                })
            self._messages.append({"role": "user", "content": results})
        raise GroundingError(["tool loop exceeded MAX_TOOL_STEPS"])

    def _validate(self, text: str, tool_pool: set[float]) -> list[str]:
        violations = []
        cited_no_signal = False
        for token in _ID_TOKEN.findall(text):
            if token not in self._known_ids:
                violations.append(f"unknown evidence ID cited: {token}")
            principle = PRINCIPLES.get(token)
            if principle is not None and principle.signal_status is SignalStatus.NO_SIGNAL:
                cited_no_signal = True
        pool = number_pool(self.bundle) | tool_pool
        for claim in unsupported_claims(text, pool):
            violations.append(
                f"number not present in bundle or tool results: {claim}"
            )
        if cited_no_signal:
            percent_claims = [c for c in numeric_claims(text) if c[1] == "%"]
            if percent_claims:
                violations.append(
                    f"confidence/percentage language on a no_signal "
                    f"principle: {percent_claims!r} — a confidence value "
                    "never launders an unmeasured inference"
                )
        return violations

    # -- explicit driver actions --------------------------------------------

    def confirm(self, staged_index: int, *, note: str | None = None) -> dict[str, Any]:
        """Apply a staged config proposal — the driver's explicit act."""
        if not (1 <= staged_index <= len(self.staged)):
            raise IndexError(f"no staged proposal #{staged_index}")
        proposal = self.staged.pop(staged_index - 1)
        change_pk = self.store.apply(
            proposal, source="chat", note=note or proposal.get("reason")
        )
        effects = {"config_applied": {"key": proposal["key"],
                                      "old": proposal["old_value"],
                                      "new": proposal["new_value"],
                                      "change_pk": change_pk}}
        self.db.add_chat_turn(
            session_id=self.session_id,
            bundle_version=self.bundle["bundle_version"],
            role="system-event",
            content=f"driver confirmed config change: {proposal['key']} "
                    f"{proposal['old_value']} -> {proposal['new_value']}",
            effects=effects,
        )
        return effects
