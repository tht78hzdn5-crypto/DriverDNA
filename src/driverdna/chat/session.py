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
from typing import Any, Iterator, Protocol

from driverdna.chat.tools import TOOL_DEFS, execute_tool
from driverdna.coach.grounding import number_pool, numeric_claims, unsupported_claims
from driverdna.coaching.ontology import PRINCIPLES
from driverdna.config import ConfigStore, DriverDNAConfig, config_snapshot
from driverdna.db import Database
from driverdna.model.taxonomy import SignalStatus
from driverdna.report.payload import build_cohort_payload, to_normalized_json

CHAT_PROMPT_VERSION = "chat-v3"

CHAT_SYSTEM_PROMPT = """\
You are DriverDNA's coaching chat. The attached bundle holds every
measurement that exists; the tools return live values from the same store.
Hard rules:
- Adopt an encouraging, engaging, and highly descriptive coaching style. Don't sound like a generic robot—sound like a seasoned, enthusiastic race engineer giving tailored, actionable advice. Provide concrete scenarios and detailed mental models for the driver to visualize.
- Never invent a measurement. Any number with a unit must come from the
  bundle or a tool result in this turn. Cite finding IDs or obs:<n> refs
  for measured claims.
- "Insufficient data" and "not measured" are expected for NO_SIGNAL fundamentals (e.g. Vision). However, per the A54 amendment, you are encouraged to provide a "Speculative Score" or guess based on proxy telemetry (e.g. steering smoothness, track position) FOR ENTERTAINMENT PURPOSES. You MUST prominently flag any such guess by stating: "This is a guess for entertainment purposes - additional data is needed for concrete grounding."
- Anything beyond the measurements is a hypothesis: label it as your
  interpretation with its basis. Racing canon may explain a finding but is
  never a measurement of this driver.
- Coaching: cite coaching_principle_id values (cp.<technique>.<name>) only
  from bundle.report.coaching (headline, secondary, self_checks) — never
  invent one, never promote one that isn't listed there. Commit to phrasing
  on measured ground; stay tentative on proxy ground; on a no_signal
  principle (self_check present), offer it as a labeled hypothesis and
  NEVER attach a confidence value or percentage to it, at any level.
- Incidents: bundle.report.incidents.events lists detected spins/offs/
  near-stops, each already carrying the engine's own classification. Only
  an incident whose coaching_principle_id is not null is generally citable.
  If the driver asks about one that isn't in your known IDs, that means the
  engine itself could not name a clean cause. Per the A54 amendment, you
  may analyze the surrounding metrics and provide a "Speculative Classification"
  or guess the cause FOR ENTERTAINMENT PURPOSES. You MUST prominently flag this
  guess by stating: "This is a guess for entertainment purposes - additional data is needed for concrete grounding."
  CRITICAL: Never cite the incident:<id> in your response for unclassified incidents, as it will fail grounding validation.
  When an incident IS citable, explain the engine's own classification
  and what it suggests practicing — you narrate its verdict, you never
  pick or override it. Every incident is one lap's event (N=1), never a
  claim about the driver in general.
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
    r"\b(?:obs:\d+|incident:\d+|(?:vs-self|vs-principle|vs-reference):[A-Za-z0-9_:.\-()]+"
    r"|cp\.[A-Za-z_]+\.[A-Za-z_]+)"
)


class ChatProvider(Protocol):
    def chat_step(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """One model step: {"text": str | None, "tool_calls": [{"id", "name", "args"}]}."""
        ...


class ClaudeChatProvider:
    def __init__(self, model: str, max_tokens: int = 16000, api_key: str | None = None):
        """`api_key`, given, is a user's own decrypted BYOK key (SPEC.md
        A37). `api_key=None` (every non-BYOK caller): `ANTHROPIC_API_KEY`,
        env-only, unchanged."""
        import os

        if api_key is None and not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Chat requires it (env only; "
                "never persisted or logged). Tests use the mocked provider."
            )
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
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


def _gemini_contents_from_messages(messages: list[dict[str, Any]]):
    """DEPLOY-SPEC Track P item 3: translate the Anthropic-shaped running
    transcript to Gemini's `contents` on every call (not incrementally —
    `messages` is the full history each time, same as ClaudeChatProvider
    receives it). Three message shapes appear in `ChatSession._messages`:

      1. `{"role": "user"|"assistant", "content": "<str>"}` — a plain text
         turn (the context bundle, the driver's message, a no-tool-call
         reply, the grounding-violation follow-up).
      2. `{"role": "assistant", "content": <raw_content>}` where
         `raw_content` is exactly what THIS module's own `chat_step` set on
         a prior call — a `types.Content` object already Gemini-shaped, so
         it round-trips by being echoed back as-is (the same reason
         ClaudeChatProvider stores Anthropic's own `response.content` as
         `raw_content`: each provider only ever has to understand its own
         echo).
      3. `{"role": "user", "content": [{"type": "tool_result",
         "tool_use_id": ..., "content": <json str>}, ...]}` — tool results,
         Anthropic-shaped as `ChatSession._drive_provider_stream` builds
         them. Gemini's FunctionResponse needs the ORIGINAL function name,
         which Anthropic's tool_result block doesn't carry — recovered here
         from the function_call parts seen earlier in the same walk.
    """
    from google.genai import types

    contents: list[types.Content] = []
    call_id_to_name: dict[str, str] = {}

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, types.Content):
            contents.append(content)
            for part in content.parts or []:
                if part.function_call is not None:
                    fc = part.function_call
                    call_id_to_name[fc.id or fc.name] = fc.name
            continue

        if isinstance(content, str):
            gemini_role = "model" if role == "assistant" else "user"
            contents.append(types.Content(role=gemini_role, parts=[types.Part(text=content)]))
            continue

        if isinstance(content, list) and content and isinstance(content[0], dict) \
                and content[0].get("type") == "tool_result":
            parts = []
            for block in content:
                call_id = block["tool_use_id"]
                name = call_id_to_name.get(call_id, "")
                try:
                    response_value = json.loads(block["content"])
                except (TypeError, json.JSONDecodeError):
                    response_value = block["content"]
                if not isinstance(response_value, dict):
                    response_value = {"result": response_value}
                parts.append(types.Part(function_response=types.FunctionResponse(
                    id=call_id, name=name, response=response_value,
                )))
            contents.append(types.Content(role="user", parts=parts))
            continue

        raise ValueError(
            f"GeminiChatProvider: unrecognized message content shape: {content!r}"
        )

    return contents


class GeminiChatProvider:
    """DEPLOY-SPEC Track P item 3: translates the Anthropic-shaped
    transcript inside this provider rather than refactoring
    `ChatSession._messages` to a neutral shape — the rejected alternative
    (a neutral internal transcript with per-provider adapters) is cleaner
    long-term but would turn M5's already-tested chat/session.py into a
    rewrite instead of a no-change; revisit if a third provider ever
    appears. Same lazy-import and env-only-key discipline as every other
    provider in this codebase."""

    def __init__(self, model: str, max_tokens: int = 16000, api_key: str | None = None):
        """`api_key`, given, is a user's own decrypted BYOK key (SPEC.md
        A37). `api_key=None` (every non-BYOK caller): `GEMINI_API_KEY`,
        env-only, unchanged."""
        import os

        if api_key is None and not os.environ.get("GEMINI_API_KEY"):
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Chat requires it (env only; "
                "never persisted or logged). Tests use the mocked provider."
            )
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def chat_step(self, system, messages, tools):
        from google.genai import types

        from driverdna.chat.gemini_tools import translate_tools

        contents = _gemini_contents_from_messages(messages)
        gemini_tools = [translate_tools(tools)] if tools else None
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self._max_tokens,
            tools=gemini_tools,
            # DriverDNA drives its own tool loop (ChatSession
            # ._drive_provider_stream) with full grounding/audit on each
            # call — the SDK must never execute a function itself.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._generate_with_backoff(contents, config)

        function_calls = response.function_calls or []
        if function_calls:
            tool_calls = [
                {"id": fc.id or f"{fc.name}:{i}", "name": fc.name, "args": dict(fc.args or {})}
                for i, fc in enumerate(function_calls)
            ]
            model_content = (
                response.candidates[0].content if response.candidates else None
            )
            return {"text": None, "tool_calls": tool_calls, "raw_content": model_content}

        text = response.text or ""
        if not text:
            # DEPLOY-SPEC Track P item 5: never a silently empty reply — it
            # would enter the grounding validator and be rejected, blaming
            # the wrong thing (a violation, not a provider failure).
            raise RuntimeError(
                "Gemini returned neither text nor a tool call for this turn"
            )
        return {"text": text, "tool_calls": [], "raw_content": None}

    def _generate_with_backoff(self, contents, config):
        """Bounded exponential backoff on HTTP 429 (DEPLOY-SPEC Track P
        item 5: free-tier RPM is low). Any other error propagates
        immediately — only rate-limiting is retried here."""
        import time

        from google.genai import errors as genai_errors

        delay_s = 1.0
        last_error: Exception | None = None
        for _ in range(5):
            try:
                return self._client.models.generate_content(
                    model=self._model, contents=contents, config=config,
                )
            except genai_errors.ClientError as e:
                if getattr(e, "code", None) != 429:
                    raise
                last_error = e
                time.sleep(delay_s)
                delay_s *= 2
        raise RuntimeError(
            "Gemini rate limited (429) after repeated backoff"
        ) from last_error


def make_chat_provider(
    config: DriverDNAConfig, *, api_key: str | None = None
) -> ChatProvider:
    """Selects Claude or Gemini per `config.coach.provider` — the one place
    this branch lives, reused by the CLI's `chat` command and `ui/api.py`'s
    equivalent factory (SPEC.md A37: `api_key`, given, is a user's own
    decrypted BYOK key; None uses the env-only server key/fallback, the
    original behavior)."""
    if config.coach.provider == "gemini":
        return GeminiChatProvider(config.coach.gemini_model, config.coach.max_tokens, api_key=api_key)
    return ClaudeChatProvider(config.coach.model, config.coach.max_tokens, api_key=api_key)


def build_chat_bundle(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig
) -> dict[str, Any]:
    """Deterministic context bundle — a known, inspectable state. chat-v3
    (Track B3, docs/UI-V3-PLAN.md) lifts the M5-era exclusion: incidents now
    ride in the bundle like every other section, citable through the same
    ChatSession._known_ids mechanism as findings and coaching principles —
    but only the classified ones (ChatSession.__init__ only admits an
    incident_id whose coaching_principle_id is not null), so an
    unclassified/external incident is structurally uncitable rather than
    citable-but-rule-forbidden — the same "engine names it or it doesn't
    exist to the model" discipline the rest of the grounding contract uses."""
    report = build_cohort_payload(db, driver=driver, car=car, track=track, config=config)
    bundle_version = report["payload_version"]
    coach_runs = db.coach_history(driver=driver, car=car, track=track)
    return {
        "prompt_version": CHAT_PROMPT_VERSION,
        "bundle_version": bundle_version,
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
        # Track B3: only a classified incident becomes citable — an
        # unclassified/external one (coaching_principle_id null) is
        # structurally absent from _known_ids, so citing its incident_id
        # is rejected the same way an unknown finding ID already is. This
        # is stricter than the coach's own structured-output rule (which
        # lets the AI mention an unclassified incident's bare facts while
        # forbidding only an explained cause) but is the mechanically
        # simple, unambiguous enforcement for chat's free-text grounding —
        # additive only, never loosening an existing rejection.
        for e in self.bundle["report"].get("incidents", {}).get("events", []):
            principle_id = e.get("coaching_principle_id")
            if principle_id:
                self._known_ids.add(e["incident_id"])
                self._known_ids.add(principle_id)

    # -- one driver turn ----------------------------------------------------

    def ask(self, text: str) -> dict[str, Any]:
        """One driver turn. Thin wrapper draining `ask_stream` to its
        terminal event — the generator is the single implementation shared
        with the SSE display path (UI-SPEC decision 4, U3)."""
        final = None
        for event in self.ask_stream(text):
            final = event
        if final["type"] == "error":
            return {"error": final["error"]}
        return {"text": final["text"], "evidence": final["evidence"],
                "effects": final["effects"], "staged": final["staged"]}

    def ask_stream(self, text: str) -> Iterator[dict[str, Any]]:
        """Generator form of one driver turn, for SSE progress display
        (UI-SPEC decision 4): ``thinking`` -> ``consulting_tool``* ->
        ``validating`` -> ``response``|``error``, repeating the
        thinking/consulting/validating cycle once more on a rejected first
        attempt. Text never streams token-by-token — the whole reply is
        mechanically validated before the terminal ``response`` event
        fires; a rejected-then-failed turn yields ``error``, never partial
        text. `ask()` is a thin wrapper that drains this to its last event.
        """
        self.db.add_chat_turn(
            session_id=self.session_id,
            bundle_version=self.bundle["bundle_version"],
            role="driver", content=text,
        )
        self._messages.append({"role": "user", "content": text})
        yield {"type": "thinking"}

        try:
            violations: list[str] = []
            for attempt in (1, 2):
                try:
                    reply, tool_pool, effects = yield from self._drive_provider_stream()
                except GroundingError as e:  # MAX_TOOL_STEPS exceeded
                    violations = e.violations
                    break
                yield {"type": "validating"}
                violations = self._validate(reply, tool_pool)
                if not violations:
                    cited = set(_ID_TOKEN.findall(reply))
                    self.db.add_chat_turn(
                        session_id=self.session_id,
                        bundle_version=self.bundle["bundle_version"],
                        role="assistant", content=reply,
                        evidence_cited=sorted(cited), effects=effects,
                    )
                    yield {"type": "response", "text": reply, "evidence": sorted(cited),
                           "effects": effects, "staged": list(self.staged)}
                    return
                if attempt == 1:
                    self._messages.append({
                        "role": "user",
                        "content": "GROUNDING VIOLATIONS — regenerate, citing only "
                                   "IDs from the bundle and numbers from the bundle "
                                   f"or tool results: {'; '.join(violations)}",
                    })
                    yield {"type": "thinking"}

            error_text = (
                "response rejected by the grounding contract (after one "
                f"regeneration): {'; '.join(violations)}"
            )
            self.db.add_chat_turn(
                session_id=self.session_id,
                bundle_version=self.bundle["bundle_version"],
                role="system-event", content=error_text,
            )
            yield {"type": "error", "error": error_text}
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_text = f"backend generation failed: {type(e).__name__}: {e}"
            self.db.add_chat_turn(
                session_id=self.session_id,
                bundle_version=self.bundle["bundle_version"],
                role="system-event", content=error_text,
            )
            yield {"type": "error", "error": error_text}

    def _drive_provider_stream(self) -> Iterator[dict[str, Any]]:
        """Yields ``consulting_tool`` audit events as each read-only tool
        call executes; returns (text, tool_pool, effects) as its generator
        return value (consumed by `yield from` in `ask_stream`)."""
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
                yield {"type": "consulting_tool", "tool": call["name"], "args": call["args"]}
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
