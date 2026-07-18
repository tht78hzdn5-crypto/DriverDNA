"""PrincipleDetectors: canonical technique checks, source-tagged vs-principle.

Built in M2. Each detector is threshold-configurable and carries a
plain-language rationale in output:
  1. Brake release should taper through turn-in.
  2. Throttle-brake overlap ~ 0.
  3. One steering input entry -> apex.
  4. Throttle monotonic after pickup.
  5. Bounded coast window between brake release and throttle pickup.
"""
