"""Incident detection + characterization (deterministic).

Every other telemetry tool treats a spin or an off as noise to be filtered.
DriverDNA's thesis is the opposite — an incident is the single richest
driver-behaviour signal on a lap — so it is *measured*, not discarded:

  Layer 1 (detector.py): a lap-level scan finds incident windows from the
  telemetry the parser already carries (near-stop, off-track surface, and a
  steering-reversal-with-yaw-spike snap). Config-thresholded, evidence-tagged.

  Layer 2 (classify.py): given a window, name the *mechanism* (trail-brake /
  lift-off / power-on oversteer, understeer-off, external kerb/bump) from the
  channel state at onset — confidence-qualified, decomposable to those
  channels, and 'unclassified' whenever the signature is ambiguous.

The engine diagnoses; it never guesses. The coaching layer that *explains*
these classifications ("why, and what to do") is a separate, later pass that
cites this output — it is not built here. A single incident is characterised
as an event ("this lap showed X"), never generalised into a trait; a pattern
across incidents needs N and goes through the normal gates.
"""

from driverdna.incidents.detector import Incident, scan_incidents

__all__ = ["Incident", "scan_incidents"]
