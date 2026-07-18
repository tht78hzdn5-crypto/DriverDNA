"""ConfigStore: typed TOML configuration with documented defaults.

Built incrementally from M1 (every threshold a milestone introduces lands here
with a documented default). The single write path for parameter changes —
whether from the CLI or a confirmed chat proposal (M5) — each change versioned
and reversible. See docs/SPEC.md, "CLI and configuration".
"""
