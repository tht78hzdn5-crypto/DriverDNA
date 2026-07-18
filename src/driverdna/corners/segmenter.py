"""CornerSegmenter: per-lap corner spans and phase landmarks.

Built in M1. Detection from sustained braking and/or steering activity
(gear-0 spans excluded); short gaps merged; landmarks per corner: entry,
brake start, peak brake, brake release, turn-in, minimum-speed apex, throttle
pickup, full throttle, exit. Multi-apex complexes are represented identically
on every lap — cross-lap consistency outranks the representation choice.
All thresholds injected from config with documented defaults.
"""
