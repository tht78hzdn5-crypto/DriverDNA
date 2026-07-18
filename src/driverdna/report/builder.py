"""ReportBuilder: Markdown + JSON + static HTML from deterministic findings.

Built in M4. JSON is normalized for determinism (sorted keys, fixed float
precision, no wall-clock timestamps in the payload body). HTML is one
self-contained file per report plus a rolling driver.html: inline CSS, inline
SVG charts (cumulative loss by technique, per-class breakdown, session trend);
no server, no external assets, no build step.
"""
