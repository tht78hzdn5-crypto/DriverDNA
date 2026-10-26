# DriverDNA — Coaching Fundamentals Review & Tendency-Layer Proposal

**Status: DESIGN / REVIEW — awaiting owner reaction before any build**
(the same gate `docs/COACHING.md` itself passed through as M7's design stage).
This document changes no engine, coaching, or UI behavior. Its only normative
content is a **draft** SPEC amendment (§6), unratified and NOT applied to
`docs/SPEC.md`.

**Date:** 2026-10-08 · **Scope:** code/doc investigation of the fundamentals
taxonomy and coaching layer, against a racing-school curriculum assembled
from published school material (§2). **Corpus examined:** the hosted copy's
282-lap, 5-cohort corpus and its generated reports of 2026-10-08.

**Owner's brief:** *"Investigate the racing fundamentals. The coaching needs
more. The analysis should basically be 'if a racing school's material was
absorbed and explained like you're actually talking to your regular
instructor because it knows your tendencies.'"*

---

## 1. Inventory — what exists

### 1.1 Fundamentals and techniques (`src/driverdna/model/taxonomy.py`, `pyramid-v1`)

Seven fundamentals, 20 techniques, 18 metrics (`metrics/technique.py`), 5 detectors (`metrics/detectors.py`). Every metric and detector maps to exactly one technique; each technique carries a tri-state `signal_status` (measured / proxy / no_signal). A fundamental's status is strict: MEASURED requires *every* technique measured.

| Fundamental | Status | Techniques (signal) | Measured by |
|---|---|---|---|
| **braking** | measured | brake_point_selection (m), brake_application (m), brake_release (m), trail_braking (m), pedal_overlap (m) | brake_point_dist_pct; brake_application_rate, brake_peak; brake_release_duration_s + `brake-release-taper`; trail_brake_overlap_s; throttle_brake_overlap_s + `throttle-brake-overlap` |
| **rotation** | measured | turn_in (m), steering_smoothness (m), rotation_efficiency (m), coasting (m) | turn_in_dist_pct + `one-steering-input`; steering_corrections, steering_smoothness_dps2; yaw_peak_rate, min_speed_kmh, apex_dist_pct; coast_s + `coast-window` |
| **corner_exit** | measured | throttle_pickup (m), throttle_modulation (m), exit_acceleration (m) | throttle_pickup_dist_pct + `throttle-monotonic`; throttle_modulation_count; full_throttle_dist_pct, exit_accel_ms2 |
| **vehicle_management** | proxy | abs_usage (m); tire_utilization, weight_transfer, slip_management (all no_signal) | abs_active_ratio only |
| **consistency** | measured | repeatability | pooled per-unit normalized CV across all measured metrics (no phases/detectors of its own) |
| **commitment** | proxy | entry_commitment | brake_point_dist_pct CV — a stand-in, labeled as such everywhere |
| **vision** | no_signal | eye_line | nothing — no eye-tracking channel exists; never inferred, never scored |

Scoring (`model/scoring.py`, dm-v2): each fundamental = weighted adherence / opportunity / consistency components; opportunity comes from cumulative loss in the fundamental's corner phases (entry→braking+commitment, mid→rotation, exit→corner_exit). Beliefs persist in `driver_beliefs` — **one row per (driver, fundamental, scoring-model version), upserted**: a live projection of current evidence, explicitly *not* an append-only history (db.py, `save_belief` docstring).

### 1.2 Coaching ontology (`src/driverdna/coaching/ontology.py`, `coach-onto-v4`)

**Nine principles for 20 techniques.** Each principle is static, versioned data: a declarative gate, a `driving_principle` (the physics), a `coaching_expression` (the words), a `drill`, a `strength_expression` (A51), and an `evidence_binding`. Per AGENTS.md, all driver-facing words live here and in `coaching/engine.py` / `explain.py` — never in the SPA, never generated.

| Principle | Fundamental | Gate | Bands on |
|---|---|---|---|
| cp.brake_release.finish_the_front | braking | DetectorGate(`brake-release-taper`) | entry seconds lost |
| cp.pedal_overlap.clean_handoff | braking | DetectorGate(`throttle-brake-overlap`) | entry seconds |
| cp.turn_in.one_commitment | rotation | DetectorGate(`one-steering-input`) | mid seconds |
| cp.coasting.always_working | rotation | DetectorGate(`coast-window`) | mid seconds |
| cp.rotation_efficiency.carry_the_middle | rotation | FindingGate(shown mid-phase vs-self opportunity) | mid seconds |
| cp.throttle_pickup.roll_it_on | corner_exit | DetectorGate(`throttle-monotonic`) | exit seconds |
| cp.repeatability.same_lap_twice | consistency | MetricCVGate(all measured metrics, `consistency_cv_floor`) | pooled normalized CV |
| cp.entry_commitment.trust_the_proxy | commitment (proxy) | MetricCVGate(brake_point_dist_pct, `commitment_cv_floor`) | entry seconds |
| cp.eye_line.look_further | vision (no_signal) | AlwaysEligible | none — quiet self-check only, never headline |

All five detectors have a principle. The uncoached techniques are the metric-only ones: **brake_point_selection, brake_application, trail_braking, steering_smoothness, throttle_modulation, exit_acceleration, abs_usage** — measured, scored, and silent. `vehicle_management` has **zero** principles; `vision` has only the self-check.

### 1.3 Selection and prioritization (`coaching/engine.py`, `coaching/rollup.py`)

- Per cohort (car, track): every (principle, corner) pair whose gate clears becomes a candidate, gap-banded (negligible / moderate / notable / major) by phase cumulative-loss seconds or CV band. Headline = top of the notable/major pool, ranked by band, then severity (magnitude as a multiple of its *own* scale's major floor — seconds are never compared raw against CVs), then IDs for determinism. Secondary = remaining moderate+. Negligible candidates are counted, not shown (`silent_count`).
- **Strengths** (A51): the strict complement — gate present, not clearing, with a *higher* evidence bar than faults — rendered with `strength_expression`, ranked by corner breadth. A strength and a fault can never be claimed for the same (principle, corner); a test pins that.
- **Driver-level rollup** (A51): instances grouped by principle across cohorts; a pattern is *shown* only if it fires at ≥ `min_tracks_for_rollup` tracks ("a principle that fires at more than one track is the driver, not the track" — rollup.py docstring), ranked by track breadth. No magnitude is ever combined across cohorts.
- Payloads: per-cohort report carries `coaching` {headline, secondary, self_checks, strengths, silent_count}; the driver payload carries `coaching_rollup`. The AI coach payload (`coach/payload.py`) = one cohort's report + `focus_history`. The chat bundle adds annotations, config snapshot, and the latest coach plan. The grounding validator (`coach/validate.py`, `coach/grounding.py`) rejects any number-with-unit not present in the payload's recursive number pool, any ineligible principle, any unknown evidence ID.

On the owner's real corpus, the system *does* find him: coasting fires at 5 tracks / 46 corners, one_commitment at 5 tracks / 46, same_lap_twice at 5 tracks / 94 — and his Brands Hatch headline is `cp.repeatability.same_lap_twice`.

---

## 2. Reference curriculum — what a racing school teaches

Synthesized from Ross Bentley's *Speed Secrets* / *Ultimate Speed Secrets*, the Skip Barber school's *Going Faster*, Bondurant-tradition HPDE manuals, and school practice generally (DirtFish, Speed Academy). Summarized, not quoted:

1. **Vision and reference points.** Eyes up and far ahead; look where you want to go, not where you are; every corner gets physical markers — brake point, turn-in, apex, track-out. Vision is taught *first* because every other input is downstream of it.
2. **The line and corner geometry.** Outside–inside–outside; apex placement (early vs. late) chosen by corner type and what follows; corner prioritization — the corner onto the longest straight matters most, slow corners are sacrificed for exits.
3. **Braking.** Threshold braking at the tire's limit; squeeze on, ease off; release *rate* as the rotation tool; trail braking — trading braking force for cornering force on entry; markers for repeatability.
4. **Steering economy.** Minimum steering angle, one committed input, slow hands; unwind the wheel as throttle is applied.
5. **Throttle.** Not an on/off switch: progressive squeeze, disciplined pickup point, earliest sustainable full throttle, never stab-and-lift.
6. **Weight transfer and the traction circle.** Every input is a load transfer; a tire's total grip is a single budget shared between braking, cornering, and acceleration; slip angles and how tires generate force. This is the physics layer that explains *why* 3–5 work.
7. **Car control and balance.** Recognizing and correcting understeer/oversteer; throttle steering; managing rotation rather than fearing it.
8. **Consistency and repeatability.** Same inputs at the same markers, lap after lap; consistency is the prerequisite for pace, and the thing that survives pressure.
9. **Vehicle and tire management.** Tire temperatures, pressures, wear; brake temperatures; not abusing the tires early; understanding what ABS intervention means.
10. **Mental discipline and process.** Deliberate practice: one focus per session, ignore lap time while drilling, structured debrief (what happened / why / how to change it), relaxation and breathing, adapting the same fundamentals to new cars and tracks.

---

## 3. Gap map — curriculum vs. inventory

| Curriculum item | Status in DriverDNA | Why / evidence |
|---|---|---|
| Vision & reference points | **Absent as measurement; present as etiquette** | vision = no_signal by design (no eye channel — taxonomy.py). The ontology's only offer is a labeled self-check. Reference-point *discipline* is implicitly measured (brake/turn-in/apex positions are metrics) but no principle coaches using markers. |
| Line & corner geometry | **Absent as coaching; present as measurement** | The engine measures apex/turn-in positions, minimum corner speed, per-phase loss, and classifies corners — but there is no line principle, no apex-placement coaching, and no corner-prioritization concept anywhere in the ontology. The largest single curriculum hole: schools start here after vision. |
| Braking | **Partial — strong on release, silent on application** | Principles cover release and pedal overlap. **brake_application** (threshold braking, peak pressure) and **brake_point_selection** and **trail_braking** are measured techniques with *no principle at all* — trail braking, the centerpiece of Bentley's and Skip Barber's entry teaching, is a metric (`trail_brake_overlap_s`) that can never be spoken. |
| Steering economy | **Partial** | one_commitment covers corrections at turn-in→apex via detector. steering_smoothness metrics (corrections count, dps²) exist with no principle of their own. |
| Throttle | **Covered** | roll_it_on is exactly the stab-and-lift lesson; pickup point and full-throttle point are measured (modulation/exit_acceleration lack principles, a lesser gap). |
| Weight transfer / traction circle | **Absent as a subject** | Taxonomy declares weight_transfer no_signal (no load channel in the Garage 61 CSV contract). The concept survives only as prose inside other principles' `driving_principle` text. Defensible absence — but the *teaching* (overlap of forces) is what cp.pedal_overlap and cp.brake_release are secretly about, and it is never named. |
| Car control / balance | **Absent** | No detector for excess rotation or balance events. The incidents layer classifies spins/offs after the fact and may attach an eligible principle, but there is no coaching for over-rotation (yaw_peak_rate is measured, uncoached) or understeer patterns. |
| Consistency / repeatability | **Covered as principle; broken as score (defect — see §4.6)** | same_lap_twice fires per-corner on CV gates. But the consistency *fundamental score* saturates to 0.0 on the real corpus, so the Driver Model and the coaching layer tell different stories about the same virtue. |
| Vehicle / tire management | **Weakest measured area** | Only abs_usage has signal, and it has **no principle** — vehicle_management is the one scored fundamental the coaching layer can never mention on its own evidence. Tire temp/wear: no channel, honestly absent. |
| Mental discipline / process | **Absent as content; partial as structure** | The drill format ("next session: one focus, ignore lap time") *is* deliberate-practice structure. But there is no progression (a drill never advances or escalates), no session plan, no debrief loop, no acknowledgment of prior assignments. |
| Racecraft (traffic, passing, awareness) | **Absent entirely** | No taxonomy entry. Solo-lap instrument by design (self laps only); for a multiplayer iRacing driver this is a scope absence worth naming, arguably by design. |
| Downshifting / heel-toe | **Absent** | No metric. Low relevance for iRacing GT4 (sequential, auto-blip); noted for completeness. |

**Coverage verdict:** of the ten curriculum items — fully covered: throttle, consistency (principle-level). Partial: braking, steering, vehicle management, mental process. Absent: vision (by design), line/geometry, weight-transfer-as-subject, car control, racecraft. The ontology speaks 9 principles against 20 measured-or-declared techniques; **7 measured techniques have no voice**, including trail braking and brake application — the two entry-phase skills schools weight most heavily after vision and line.

---

## 4. Personalization audit — does the coaching know the driver?

**Method:** traced every mechanism that could carry driver-specific memory or adaptation: `coaching/engine.py`, `coaching/rollup.py`, `model/scoring.py` (`_trend`), `model/history.py`, `db.py` (`coach_history`, `save_belief`, annotations), `coach/payload.py`, `coach/provider.py` (SYSTEM_PROMPT), `chat/session.py`.

### 4.1 What genuinely personalizes

- **Cross-track habit detection (rollup.py).** The same principle firing at ≥ `min_tracks_for_rollup` tracks is promoted to a driver-level pattern and ranked by breadth, on the stated reasoning that one corner at one track is the track, but the same fault at five tracks is the driver. On the owner's corpus this correctly elevates coasting (5 tracks, 46 instances) above any single-corner fault. This is the most instructor-like mechanism in the codebase.
- **Self-referential measurement.** Findings and bands are computed against *his own* lap distribution (vs-self findings, his cumulative loss); reference laps never enter self history. The standard he is held to is his own demonstrated capability — an instructor's standard.
- **Strengths (A51).** The strict complement of faults, with a higher evidence bar, means the report can say what he is *clearing*, in the ontology's own words. An instructor acknowledges what's working; a printout usually doesn't.
- **Annotations.** The driver can mark a finding acknowledged/intentional; annotated findings leave the priority pool (still citable). A real feedback channel — the system can be told "I know" and stops leading with it. Finding-granular only.
- **Chat bundle.** Chat receives annotations and the latest coach plan, so a conversation can reference the last plan. The report itself cannot (see 4.2).

### 4.2 What does not — the amnesia, with evidence

**(a) Coaching eligibility has no time dimension.** `eligible_principles` is documented as a "Pure function of DB state + config," and the detector/metric tables it reads (`db.self_detector_table`, `db.self_metric_table`) pool **all** laps in the cohort — no date, session, or era predicate exists anywhere in the coaching path. A fault committed in his first recorded session and one committed yesterday weigh identically. The coaching layer mathematically cannot distinguish "did this in March, fixed by June" from "did this on his last lap."

**(b) Trend exists and is never read by coaching.** `_trend()` (scoring.py) computes improving/stable/declining per fundamental from two date-buckets of dated laps; `model/history.py` (A36) generalizes it to an N-bucket series for the UI chart. Neither is an input to coaching: `select_coaching(candidates, strengths, *, config)` — the signature has no trend, no beliefs, no history — and the coaching payload carries no trend field. In the owner's real payload every belief trend reads "stable," and the coaching says nothing about any of them either way.

**(c) The one artifact named "history" is titles, unread.** Prior AI coaching *is* persisted (`coach_outputs`), but `db.coach_history()` reduces it to plan titles only:

```python
"plan_titles": [p.get("title") for p in output.get("coaching_plan", [])],
```

and while `build_coach_payload` ships it as `focus_history`, the coach's SYSTEM_PROMPT (`coach/provider.py`, coach-v3) **never mentions `focus_history`** — no instruction to follow up, avoid repeating an assignment, or acknowledge progress. Memory exists in the schema and is functionally inert. Beliefs have the same property at the model layer: `driver_beliefs` is an upserted projection ("not an append-only history"), so even scores leave no trail inside the DB — the N-bucket history is recomputed from laps each time, and coaching doesn't use it anyway.

**(d) No recurrence or transition concept.** Nothing records that a principle headlined a previous report, fired for the Nth consecutive computation, or *stopped* firing. If the owner fixes his coasting at a corner, the candidate simply vanishes and (with enough evidence) a strength appears — but no sentence can say "this used to fire here," because no state remembers that it did. Progress is representable only as a fresh snapshot that happens to differ from one nobody kept.

**(e) Drills cannot adapt.** `drill` is one static string per principle (ontology.py). The candidate carries car, track, corner_id (an anonymized C-number — corners have no names in the payload), band, magnitude, and n; the drill text uses none of them. The same words serve a notable instance and a major one, a first occurrence and a fiftieth, a slow corner and a fast one (corner speed class exists in `corners/classify.py` but is not in the coaching payload). There is no second-level drill for a persistent pattern — an instructor escalates or changes the drill; this system repeats it verbatim forever.

**(f) Sessions are invisible.** The corpus knows 53 sessions (census gates on them), but coaching never groups by session: warm-up laps vs. late-session laps, first-visit vs. return-visit patterns, are unrepresentable.

**Interchangeability test:** swap the owner's laps for another GT4 driver's with the same aggregates and every sentence in his report is identical except numbers and corner IDs. Personalization today lives entirely in *which* principles fire and their magnitudes — never in what is said, what is remembered, or what happens next.

### 4.3 Verdict

The coaching knows the driver's **aggregate** and his **cross-track habits as a snapshot**; it does not know his **trajectory**, his **assignments**, or **whether he did them**. Statistically valid, evidentially impeccable — and interchangeable. It is a printout of a very good instrument, not yet an instructor.

### 4.4 Defect flagged (for the scoring investigation's BUG-LOG — not logged here, per collision discipline)

On the real 282-lap corpus, `consistency` scores **0.0 at 100% confidence** and `vehicle_management` scores **0.0** (it is scored on the consistency component alone, weight 1.0 — payload `basis_reason`), while `vehicle_management` trend simultaneously reads "improving." Independent replication of the engine's pooling gives pooled normalized CV 2.39 vs. the dm-v2 ceiling of 2.0 → clamped to zero; the "% lap" unit mean is 6.77× its reference, driven by near-zero-mean position metrics at small n. (Filed by the concurrent scoring investigation as BUG-042/043/044; cross-referenced here rather than duplicated, per the one-defect-one-entry rule.)

---

## 5. Proposal — "the regular instructor," inside the constitution

The constitution is not the obstacle; it is the design spec. An instructor's memory is *also* evidence-based: "you've done this at four tracks now" is a measurement claim, and this codebase already knows how to make measurement claims legally — compute them deterministically, put them in the payload with N and evidence IDs, and let the validator do the rest. What is missing is a **longitudinal aggregation layer**, not permission to improvise.

### 5.1 The Tendency layer (deterministic, versioned, decomposable)

A **tendency** is a per-(driver, principle) longitudinal record computed by the engine from quantities it already produces:

- **Eras.** Bucket the driver's dated laps exactly as A36 score history already does (`model/history.py`'s equal-count date buckets). Run the existing eligibility/strength machinery per era — no new measurement kind; a new *aggregation* of existing ones, the same legal status A36 claimed for score history ("deliberately produces no new kind of number").
- **State per tendency:** `new` (first era fired) · `recurring` (fired in ≥2 eras) · `persistent` (fired in the most recent era and ≥ a config share of all eras) · `improving` (fired, but band/magnitude falling across eras in its own magnitude_kind) · `resolved` (previously fired, now clearing as a strength or below gate for K consecutive eras) · `dormant` (not fired recently, not yet resolved). Every state carries eras_fired/eras_total, first_seen, last_seen, per-era band, and the era instances' evidence IDs. Thresholds live in config, like every other threshold in this repo.
- **Persistence.** A `driver_tendencies` table shaped like `driver_beliefs` (owner-scoped, versioned by a `TENDENCY_MODEL_VERSION`), storing the projection *and* first_seen — the one deliberate departure from beliefs' upsert-amnesia, and the reason this needs a SPEC amendment rather than silent code.
- **Payload.** A `tendencies` section in the driver payload and per-cohort coaching payload. Because `grounding.number_pool` is recursive over the whole payload, every tendency number ("fired in 4 of 5 eras") becomes legally citable by the AI **with zero validator changes**. Tendency-aware phrasing is constitutional *by construction*: the engine states the history; the AI may only narrate engine-stated history.

### 5.2 Words stay where words live

- Ontology gains, per principle, optional tendency-framed variants keyed by state (rendered deterministically): e.g. for `persistent` — a framing that names it as the habit, not the corner; for `resolved` (strength side) — text that acknowledges the fix *and cites the era it stopped*. Plus `drill_followup`: the escalated second assignment for a persistent pattern, so the system stops repeating the identical drill verbatim.
- The coach SYSTEM_PROMPT gains exactly one instruction class: when `payload.tendencies` marks a principle recurring/persistent, the plan must acknowledge the history using tendency fields only; when resolved, acknowledge the fix. `PROMPT_VERSION` bump; validator unchanged — ineligible principles and out-of-pool numbers are already mechanical rejections, and tendency states arrive as payload data.

### 5.3 Staging

- **Stage 0 — this review** + the draft SPEC amendment (§6) for owner approval. No behavior change.
- **Stage 1 — era recurrence in the driver rollup (no new table, no AI change).** Compute per-era eligibility for rollup patterns; annotate each pattern with eras_fired/eras_total and a state label; render one line in the driver report. Reuses A36 bucketing + existing eligibility. This is the smallest increment (§5.5).
- **Stage 2 — persistence + words.** `driver_tendencies` table, resolved-state detection via the strength complement across eras, ontology tendency variants and `drill_followup`, payload section (additive; `PAYLOAD_VERSION` bump per precedent).
- **Stage 3 — narration + session dimension.** Coach/chat prompt wiring (focus_history superseded by tendencies as the memory the prompt actually instructs on), and session-aware slicing (early- vs. late-session, first-visit vs. return) as a second tendency dimension.

### 5.4 Explicitly out of bounds

- The AI asserting any tendency, recurrence, or progress claim not present in `payload.tendencies` — the validator's number pool and principle-eligibility checks already reject the numeric half of this; the state labels join the payload so the verbal half is checkable too.
- Any tendency state without evidence IDs and era counts.
- A54 speculative content (vision guesses, incident guesses) contributing to tendency state — a guess must never become a memory.
- Loosening `coach/grounding.py` or `coach/validate.py` in any way. The proposal adds payload data and ontology text; it touches no enforcement.

### 5.5 The smallest first increment

Stage 1 alone changes the next real report the owner reads. Today's rollup says, in effect: *"Coasting — 46 instances, 5 tracks."* With era recurrence it says: *"Coasting — fired in every era since your first recorded sessions, at 5 tracks; currently notable at 9 corners. This is the habit, not a corner — and it isn't fixed yet."* Every number in that sentence is engine-computed from machinery that already exists (dated-lap buckets + per-cohort eligibility), no schema migration, no AI involvement, no validator change. That one line is the difference between a printout and an instructor who has seen him drive before.

---

## 6. Draft SPEC amendment (DRAFT — unratified, for owner approval; not applied to SPEC.md)

> **A55 (DRAFT)** — **Tendency layer.** A *tendency* is a deterministic, versioned (`TENDENCY_MODEL_VERSION`), per-(driver, coaching-principle) longitudinal state — one of `new / recurring / persistent / improving / resolved / dormant` — computed from era-bucketed coaching eligibility and strength complements, where eras are the A36 date-ordered lap buckets. Every tendency state ships with eras_fired/eras_total, first_seen/last_seen, per-era gap band in the principle's own magnitude_kind, and evidence IDs, and is decomposable to the era instances that produced it. The AI layer may reference tendency state only as payload data under the existing grounding contract; it may not assert recurrence, progress, or resolution that the payload does not state. Speculative (A54) content never contributes to tendency state. Tendency thresholds live in config. This adds an aggregation over existing measurements; it creates no new measurement kind and changes no existing score.

---

## Sources for §2 (curriculum)

- Ross Bentley, *Speed Secrets* / *Ultimate Speed Secrets* — speedsecrets.com; chapter summaries via manuals.plus (Ultimate Speed Secrets) and bookey.app.
- Skip Barber Racing School, *Going Faster: Mastering the Art of Race Driving* — school curriculum summaries (threshold braking, line theory, trail braking, over/understeer management, progression from smooth inputs to consistency).
- Bondurant-tradition HPDE manuals (friction/traction circle, slip angles, weight transfer) via Scribd-hosted school manuals.
- DirtFish, "Why we start every student on the skid pad" (weight transfer first principles); Speed Academy driving-techniques summary (smoothness and weight transfer).

All curriculum material is summarized in my own words; nothing is quoted at length.
