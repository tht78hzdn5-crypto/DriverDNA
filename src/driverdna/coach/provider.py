"""CoachProvider interface + Claude/Gemini implementations (M4, DEPLOY-SPEC
Track P).

Provider-abstracted so every test runs against a mock; each real
implementation reads its own env-only API key — never persisted, printed,
or logged — and imports its SDK lazily so nothing else needs it installed.
On-demand only: nothing in DriverDNA calls a provider without an explicit
`coach` or `chat` invocation.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from driverdna.config import DriverDNAConfig

PROMPT_VERSION = "coach-v3"

SYSTEM_PROMPT = """\
You are the coaching layer of DriverDNA, a deterministic racing-telemetry
instrument. The attached JSON payload contains every measurement you may
rely on, plus payload.coaching: the deterministically eligible, ranked,
gap-banded coaching principles you speak from (docs/COACHING.md). Hard
rules:
- You never invent a measurement. Every number with a unit you write must
  appear in the payload. Cite finding_id / evidence IDs from the payload only.
- Findings marked suppressed are below their confidence gates: you may note
  they exist but must not present them as established.
- Anything beyond the measurements is a hypothesis: label it, give its
  basis and a confidence level. Every entry in the top-level "hypotheses"
  array below MUST carry a non-null "confidence" of low/medium/high — this
  applies to every hypothesis, including one about something the telemetry
  structurally cannot measure (e.g. eye movement); "the confidence that
  THIS IS THE RIGHT HYPOTHESIS is low" is exactly what "low" means there,
  so never write null or omit the field.
- "Insufficient data" is expected for NO_SIGNAL fundamentals (e.g. Vision). However, per the A54 amendment, you are encouraged to provide a "Speculative Score" or guess based on proxy telemetry (e.g. steering smoothness) FOR ENTERTAINMENT PURPOSES. You MUST prominently flag any such guess by stating: "This is a guess for entertainment purposes - additional data is needed for concrete grounding."
- For ambiguous incidents (e.g., classification "unclassified"), you may provide a "Speculative Classification" or guess the cause FOR ENTERTAINMENT PURPOSES. You MUST prominently flag this guess by stating: "This is a guess for entertainment purposes - additional data is needed for concrete grounding."
- Coaching: cite coaching_principle_id values ONLY from payload.coaching
  (headline, secondary, self_checks) — never invent one, never promote an
  ineligible one. On measured/proxy ground, commit to the phrasing like a
  coach who's sure (proxy still stays tentative in tone). On no_signal
  ground (self_check present, signal_status "no_signal"), offer it exactly
  as a labeled hypothesis with its self-check — NEVER attach a confidence
  value or percentage to it, at any level; that is a mechanical rejection.
  This no-confidence rule is scoped ONLY to a no_signal coaching_priorities
  entry — it never applies to the separate top-level "hypotheses" array,
  which always requires confidence per the rule above.
- Incidents: payload.incidents.events lists detected spins/offs/near-stops.
  Each already carries the engine's own classification AND its
  coaching_principle_id (or null). You may explain ONLY an incident whose
  coaching_principle_id is not null, and your incident_explanations entry's
  coaching_principle_id MUST be copied exactly from that event — you do not
  choose or override it, you only narrate why the engine's classification
  makes sense and what it suggests practicing. An incident with
  coaching_principle_id null (unclassified/external) means the engine itself
  could not name a cause; do not explain it, do not guess one. Every
  explanation is about that ONE lap's event, never a claim about the driver
  in general. Every incident_explanations entry's "evidence_ids" MUST
  include that entry's own "incident_id" as one of its elements (e.g.
  "evidence_ids": ["incident:1", ...]) — the incident is its own required
  citation, in addition to any other evidence you reference.
Respond with ONLY a JSON object, no prose around it, in this shape:
{
  "measured_priorities": [
    {"finding_id": "...", "evidence_ids": ["..."], "why": "..."}
  ],
  "coaching_priorities": [
    {"coaching_principle_id": "...", "corner_id": "..." or null,
     "expression": "...", "why": "...", "evidence_ids": ["..."]}
  ],
  "incident_explanations": [
    {"incident_id": "...", "coaching_principle_id": "...",
     "explanation": "...", "confidence": "low|medium|high",
     "evidence_ids": ["..."]}
  ],
  "coaching_plan": [
    {"title": "...", "focus": "...", "actions": ["..."]}
  ],
  "hypotheses": [
    {"statement": "...", "basis": "...", "confidence": "low|medium|high",
     "evidence_ids": ["..."]}
  ]
}
"""


class CoachProvider(Protocol):
    def complete(self, system_prompt: str, user_content: str) -> str:
        """Return the model's raw text response."""
        ...


class ClaudeCoachProvider:
    def __init__(self, model: str, max_tokens: int = 16000, api_key: str | None = None):
        """`api_key`, given, is passed straight to the SDK client instead of
        the env var (SPEC.md A37, BYOK) — a user's own decrypted key,
        already resolved by the caller (never read from a request body
        here). `api_key=None` (every non-BYOK caller) is the original
        behavior: `ANTHROPIC_API_KEY`, env-only, unchanged."""
        if api_key is None and not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. The coach requires it (env "
                "only; never persisted or logged). All tests use the mocked "
                "provider instead."
            )
        import anthropic  # lazy: only a live coach run needs the SDK

        self._client = anthropic.Anthropic(api_key=api_key)  # None -> reads the env var itself
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system_prompt: str, user_content: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return "".join(
            block.text for block in response.content if block.type == "text"
        )


class GeminiCoachProvider:
    """DEPLOY-SPEC Track P: same lazy-import discipline as the Claude
    provider above (`google-genai` imported inside `__init__`, never at
    module import), same env-only key (`GEMINI_API_KEY`), absent -> a loud
    RuntimeError naming the variable. All tests use the mocked provider
    instead; nothing about grounding is provider-specific (coach/validate.py
    validates the returned text against the payload's own number pool and
    ID universe regardless of which model produced it)."""

    def __init__(self, model: str, max_tokens: int = 16000, api_key: str | None = None):
        """`api_key`, given, is a user's own decrypted BYOK key (SPEC.md
        A37), passed straight to the SDK client instead of the env var.
        `api_key=None` (every non-BYOK caller): `GEMINI_API_KEY`, env-only,
        unchanged."""
        if api_key is None and not os.environ.get("GEMINI_API_KEY"):
            raise RuntimeError(
                "GEMINI_API_KEY is not set. The coach requires it (env "
                "only; never persisted or logged). All tests use the mocked "
                "provider instead."
            )
        from google import genai  # lazy: only a live coach run needs the SDK

        self._client = genai.Client(api_key=api_key)  # None -> reads GEMINI_API_KEY itself
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system_prompt: str, user_content: str) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=self._max_tokens,
            ),
        )
        return response.text or ""


def make_coach_provider(
    config: "DriverDNAConfig", *, api_key: str | None = None
) -> CoachProvider:
    """Selects Claude or Gemini per `config.coach.provider` — the one place
    this branch lives, reused by the CLI's `coach` command and the API's
    equivalent factory (SPEC.md A37: `api_key`, given, is a user's own
    decrypted BYOK key; None uses the env-only server key/fallback, the
    original behavior)."""
    if config.coach.provider == "gemini":
        return GeminiCoachProvider(config.coach.gemini_model, config.coach.max_tokens, api_key=api_key)
    return ClaudeCoachProvider(config.coach.model, config.coach.max_tokens, api_key=api_key)
