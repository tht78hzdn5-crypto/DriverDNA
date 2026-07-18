"""TechniqueAnalyzer: deterministic per-corner/per-lap metrics.

Built in M2. Braking (brake-point distance, application rate, peak, release
duration/shape, trail overlap with steering, repeatability); rotation
(turn-in point, steering smoothness and correction count, yaw response,
minimum speed, repeatability); exit (throttle-pickup distance, modulation,
full-throttle distance, exit acceleration); vehicle management (ABS rate,
acceleration proxies only); consistency (lap-to-lap variance of everything).
Explicitly unavailable and never inferred: tire slip/utilization, vision.
"""
