"""AI coaching: provider interface, Claude implementation, one-shot plan (M4).

CoachProvider is provider-abstracted (ANTHROPIC_API_KEY, env only). The coach
payload is versioned and deterministic; structured output is locally validated
— unknown evidence IDs, unsupported metric claims, malformed rankings, or
hypotheses presented as measurements are rejected. On-demand only; no
automatic refresh. Tests run against a mocked provider.
"""
