"""CoachChat: grounded interactive coaching over deterministic findings (M5).

Deterministically assembled, versioned context bundle; read-only tool surface
returning real DB values (finding lookup, metric distributions, corners in
class, config values); the only write is confirmation-gated
propose_config_change, staged through ConfigStore. Grounding is enforced
mechanically: structured evidence-ID citations, a numeric-claim validator
(numbers in prose must match bundle/tool values within tolerance), unknown-ID
rejection, one regeneration then a visible error. "Insufficient data" is a
first-class answer. Transcripts persisted with bundle version and effects.
"""
