"""CornerClassifier: speed-band class per corner identity, with hysteresis.

Built in M1. Class from the median minimum corner speed across laps (never
per lap). Default bands, configurable: slow < 90 km/h, medium 90-150,
fast > 150 (channel is m/s; converted). Hysteresis: once assigned, a class
changes only if the median moves a configured margin past the band edge, and
the change is reported as an event. Raw min speeds stored so bands can be
re-derived.
"""
