"""CoachProvider interface + Claude implementation (M4).

Provider-abstracted so every test runs against a mock; the Claude
implementation reads ANTHROPIC_API_KEY from the environment only — never
persisted, printed, or logged — and imports the SDK lazily so nothing else
needs it installed. On-demand only: nothing in DriverDNA calls a provider
without an explicit `coach` or `chat` invocation.
"""

from __future__ import annotations

import os
from typing import Protocol

PROMPT_VERSION = "coach-v2"

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
  basis and a confidence level.
- "Insufficient data" is a valid and expected statement.
- Coaching: cite coaching_principle_id values ONLY from payload.coaching
  (headline, secondary, self_checks) — never invent one, never promote an
  ineligible one. On measured/proxy ground, commit to the phrasing like a
  coach who's sure (proxy still stays tentative in tone). On no_signal
  ground (self_check present, signal_status "no_signal"), offer it exactly
  as a labeled hypothesis with its self-check — NEVER attach a confidence
  value or percentage to it, at any level; that is a mechanical rejection.
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
  in general.
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
    def __init__(self, model: str, max_tokens: int = 4000):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. The coach requires it (env "
                "only; never persisted or logged). All tests use the mocked "
                "provider instead."
            )
        import anthropic  # lazy: only a live coach run needs the SDK

        self._client = anthropic.Anthropic()  # reads the env var itself
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
