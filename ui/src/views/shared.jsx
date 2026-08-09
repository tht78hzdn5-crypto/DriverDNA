import React, { useEffect, useState } from "react";
import { get } from "../api.js";
import { fmt } from "../format.js";

// Methodology disclosure ("the arrow", SPEC.md A35): text comes from the
// engine (GET /api/explain), never hand-written per view, so the SPA and a
// future static-report equivalent can't drift onto two different
// explanations of the same figure. One shared fetch — every <Methodology>
// instance on a page reuses the same module-level promise instead of each
// firing its own request.
let _methodologyPromise = null;
function loadMethodology() {
  if (!_methodologyPromise) _methodologyPromise = get("/api/explain").catch(() => ({}));
  return _methodologyPromise;
}

// The raw text for one explain.py id, or null while loading/absent. Shared
// by <Methodology> (wraps it in a disclosure) and anything that needs the
// text rendered plainly instead — e.g. IncidentCard's inline empathy line,
// which reads oddly nested inside its own second <details>.
export function useMethodologyText(id) {
  const [text, setText] = useState(null);
  useEffect(() => {
    let alive = true;
    loadMethodology().then((all) => { if (alive) setText(all[id] || null); });
    return () => { alive = false; };
  }, [id]);
  return text;
}

// Fails closed: an id absent from the engine's dict renders nothing rather
// than a disclosure with no text. tests/test_explain.py catches a typo'd id
// at test time by cross-referencing every literal usage of this component's
// id prop, across the codebase, against the real key set — silence here is
// a caught bug, not a swallowed one.
export function Methodology({ id, label = "How is this measured?" }) {
  const text = useMethodologyText(id);
  if (!text) return null;
  return (
    <details className="disclosure">
      <summary><span className="chev" aria-hidden="true">▸</span> {label}</summary>
      <div className="disclosure-body">{text}</div>
    </details>
  );
}

// The pyramid's fixed order — foundations first, higher-order skills after
// (shared with model.jsx so the two tabs read the same way). Layout only:
// fixed regardless of score, so the order never implies a ranking. The
// *labels* are not here — they come from the payload (`belief.label`), the
// engine owning its own words.
export const FUNDAMENTAL_ORDER = [
  "braking", "rotation", "corner_exit",
  "commitment", "consistency", "vehicle_management", "vision",
];

// id -> driver-facing name, straight from the payload's driver_model section.
export function fundamentalLabels(driverModel) {
  const out = {};
  for (const [id, b] of Object.entries(driverModel?.beliefs || {})) {
    if (b.label) out[id] = b.label;
  }
  return out;
}

function orderedGroups(itemsById) {
  const known = FUNDAMENTAL_ORDER.filter((id) => itemsById[id]);
  const rest = Object.keys(itemsById).filter((id) => !FUNDAMENTAL_ORDER.includes(id));
  return [...known, ...rest.sort()];
}

// One finding. The claim and its value stay in the clear; N, spread, the
// reference depth and the detector's per-lap rationale move behind the
// disclosure arrow — reachable in one click, never deleted (A46). Nothing
// here is inside a `.num` element unless it is a real payload number: the
// rationale quotes ONE lap's figure, so it renders as prose.
export function FindingRow({ finding, slug }) {
  const cls = finding.shown && !finding.annotation ? "" : "suppressed";
  const detail = `#/finding/${slug}/${encodeURIComponent(finding.finding_id)}`;
  return (
    <div className={`finding ${cls}`}>
      <div className="head">
        <span className="desc">
          <span className="src-tag">{finding.source}</span>
          <a href={detail}>{finding.description}</a>
        </span>
        <span className="val num">
          {finding.seconds === null ? "" : `${fmt(finding.seconds)} s`}
        </span>
      </div>
      {!finding.shown && <div className="reason">{finding.gate_reason}</div>}
      {finding.annotation && (
        <div className="meta">{finding.annotation.status} by you — measurement kept</div>
      )}
      {/* A suppressed row already sits inside its group's disclosure and
          carries its gate reason inline; a second nested arrow under each
          one is the noise this change exists to remove. Its numbers stay
          reachable through the description's link to the evidence view. */}
      {finding.shown && (
      <details className="disclosure">
        <summary><span className="chev" aria-hidden="true">▸</span> Evidence</summary>
        <div className="disclosure-body">
          <div className="meta num">
            n={finding.n}
            {finding.spread !== null && <> · spread {fmt(finding.spread)}</>}
            {finding.source === "vs-reference" && finding.details?.reference_n != null && (
              <> · ref n={finding.details.reference_n}</>
            )}
          </div>
          {finding.details?.rationale && (
            <p style={{ margin: "0.4rem 0 0" }}>
              {finding.details.rationale}{" "}
              <span className="dim">(one lap — see the full evidence for the rest)</span>
            </p>
          )}
          <div style={{ marginTop: "0.4rem" }}>
            <a href={detail}>Full evidence →</a>
          </div>
        </div>
      </details>
      )}
    </div>
  );
}

// Findings grouped by racing fundamental (A46) rather than by source.
// Grouping is presentation: each row still carries its own source tag and
// its own arithmetic, and no group shows a combined figure — summing the
// per-phase losses into a per-fundamental total would be the UI computing a
// measurement, which the binding render rule forbids.
export function FundamentalSections({ findings, slug, labels, coaching, headlinePrincipleId }) {
  const byId = {};
  for (const f of findings) {
    const id = f.fundamental || "_other";
    (byId[id] = byId[id] || []).push(f);
  }
  const coachById = {};
  for (const c of coaching || []) {
    const id = c.fundamental || "_other";
    (coachById[id] = coachById[id] || []).push(c);
  }
  const ids = orderedGroups({ ...byId, ...coachById });

  return ids.map((id) => {
    const group = byId[id] || [];
    const shown = group.filter((f) => f.shown && !f.annotation);
    const annotated = group.filter((f) => f.shown && f.annotation);
    const suppressed = group.filter((f) => !f.shown);
    return (
      <div key={id} className="fgroup">
        <div className="fgroup-head">
          <span className="fgroup-name">{labels[id] || id.replace(/_/g, " ")}</span>
          <span className="fgroup-count num">{shown.length}</span>
        </div>

        {coachById[id] && (
          <CoachingSecondary
            items={coachById[id]} slug={slug}
            headlinePrincipleId={headlinePrincipleId}
          />
        )}

        {shown.map((f) => <FindingRow key={f.finding_id} finding={f} slug={slug} />)}
        {annotated.map((f) => <FindingRow key={f.finding_id} finding={f} slug={slug} />)}

        {!shown.length && !annotated.length && (
          <div className="dim" style={{ fontSize: "0.8rem", padding: "0.2rem 0 0.4rem" }}>
            Nothing clears the gates here yet.
          </div>
        )}

        {suppressed.length > 0 && (
          <details className="disclosure">
            <summary>
              <span className="chev" aria-hidden="true">▸</span>{" "}
              {suppressed.length} not shown yet — evidence gates
            </summary>
            <div className="disclosure-body">
              {suppressed.map((f) => (
                <FindingRow key={f.finding_id} finding={f} slug={slug} />
              ))}
            </div>
          </details>
        )}
      </div>
    );
  });
}

// How the grouping and the three source tags work — said once for the whole
// section, in ONE disclosure rather than four stacked ones. The texts are
// still the engine's (explain.py); only the wrapper is shared, so four rows
// of chrome don't replace the per-section repetition this change removed.
export function SourceLegend() {
  // Four fixed hook calls, not a loop — the rules of hooks apply even when
  // the list is a module constant.
  const grouping = useMethodologyText("finding.grouping");
  const vsSelf = useMethodologyText("source.vs-self");
  const vsPrinciple = useMethodologyText("source.vs-principle");
  const vsReference = useMethodologyText("source.vs-reference");
  const rows = [
    ["grouping", grouping], ["vs-self", vsSelf],
    ["vs-principle", vsPrinciple], ["vs-reference", vsReference],
  ].filter(([, text]) => text);
  if (!rows.length) return null;
  return (
    <details className="disclosure">
      <summary>
        <span className="chev" aria-hidden="true">▸</span> How this is grouped, and what the tags mean
      </summary>
      <div className="disclosure-body">
        {rows.map(([label, text]) => (
          <p key={label} style={{ margin: "0 0 0.5rem" }}>
            <span className="src-tag">{label}</span>{text}
          </p>
        ))}
      </div>
    </details>
  );
}

// Coaching (M7): the grounded plain-language layer over the raw findings.
// Everything here is a straight render of payload.coaching — the eligibility,
// ranking, and gap-band tone are the deterministic engine's; nothing here
// computes or rephrases a claim. A no_signal item (self-check) never carries
// a score, magnitude, or confidence — a hypothesis, labelled as one.
function magnitudeText(kind, value) {
  if (kind === "seconds_lost") return `${fmt(value)} s`;
  if (kind === "coefficient_of_variation") return `CV ${fmt(value, 2)}`;
  return null;
}

// The corner is the actionable part and stays in the clear; the band,
// magnitude and sample size are the supporting data and move behind the
// arrow (A46) — the same treatment findings get, so one page has one rule.
function CoachingTags({ item, slug }) {
  const mag = magnitudeText(item.magnitude_kind, item.magnitude);
  return (
    <>
      <div className="coach-tags">
        {item.corner_id && (
          <span className="chip">
            <a href={`#/corner/${slug}/${item.corner_id}`}>{item.corner_id}</a>
          </span>
        )}
        {item.thin_evidence && <span className="chip dim">thin evidence</span>}
      </div>
      <details className="disclosure">
        <summary><span className="chev" aria-hidden="true">▸</span> Why this, and how sure</summary>
        <div className="disclosure-body">
          <div className="meta num">
            {item.gap_band && <>{item.gap_band}</>}
            {mag && <> · {mag}</>}
            {" "}· n={item.n} · {item.signal_status}
          </div>
        </div>
      </details>
    </>
  );
}

export function CoachingHeadline({ headline, headline_reason, silent_count, slug }) {
  if (!headline) {
    return (
      <div className="dim" style={{ fontSize: "0.85rem" }}>
        {headline_reason || "Nothing clears the headline gate yet — insufficient data."}
        {silent_count > 0 && ` (${silent_count} principle${silent_count === 1 ? "" : "s"} tracked, not yet notable.)`}
      </div>
    );
  }
  return (
    <div className="coach-headline">
      <div className="coach-say">{headline.coaching_expression}</div>
      <div className="coach-why">{headline.driving_principle}</div>
      {headline.drill && <div className="coach-drill"><b>Try this:</b> {headline.drill}</div>}
      <CoachingTags item={headline} slug={slug} />
    </div>
  );
}

// Grouped by principle, not flattened: the same coaching principle often
// clears the gate at several corners independently (e.g. repeatability at
// 14 of them) — the deterministic engine, correctly, treats each as its own
// eligible instance. Repeating the identical paragraph 14 times is a
// presentation problem, not a data one: group so the expression/why is said
// ONCE, then list every instance's own corner/magnitude/n as compact tags —
// every number shown still traces 1:1 to its own record, nothing combined.
function groupByPrinciple(items) {
  const groups = new Map();
  for (const c of items) {
    if (!groups.has(c.coaching_principle_id)) groups.set(c.coaching_principle_id, []);
    groups.get(c.coaching_principle_id).push(c);
  }
  return [...groups.values()];
}

export function CoachingSecondary({ items, slug, limit = 4, headlinePrincipleId = null }) {
  const [shown, setShown] = useState(limit);
  if (!items.length) return <div className="dim" style={{ fontSize: "0.82rem" }}>Nothing else notable right now.</div>;
  const groups = groupByPrinciple(items);
  return (
    <>
      {groups.slice(0, shown).map((g) => {
        const head = g[0];
        // The headline already said this principle's expression/why in full;
        // repeating the identical paragraph here would read as a duplicate.
        // Its OTHER corners are still real, separate findings — worth
        // keeping, just cross-referenced instead of restated.
        const sameAsHeadline = head.coaching_principle_id === headlinePrincipleId;
        return (
          <div key={head.coaching_principle_id} className="coach-item">
            {sameAsHeadline ? (
              <div className="coach-say dim" style={{ fontWeight: 400 }}>
                Same as the headline above, also at:
              </div>
            ) : (
              <>
                <div className="coach-say">{head.coaching_expression}</div>
                <div className="coach-why">{head.driving_principle}</div>
              </>
            )}
            {g.length === 1 ? (
              <CoachingTags item={head} slug={slug} />
            ) : (
              // The fundamental is the group heading now, so naming it on
              // every chip row would repeat it once per principle.
              <div className="coach-tags">
                <span className="chip num dim">at {g.length} corners:</span>
                {g.map((c) => (
                  <span key={c.corner_id} className="chip num">
                    {c.corner_id ? <a href={`#/corner/${slug}/${c.corner_id}`}>{c.corner_id}</a> : "—"}
                    {" "}{magnitudeText(c.magnitude_kind, c.magnitude)}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
      {groups.length > shown && (
        <button className="btn small" style={{ marginTop: "0.5rem" }}
                onClick={() => setShown(groups.length)}>
          + {groups.length - shown} more principle{groups.length - shown === 1 ? "" : "s"}
        </button>
      )}
    </>
  );
}

export function CoachingSelfChecks({ items, labels = {} }) {
  if (!items.length) return null;
  return items.map((c) => (
    <div key={c.coaching_principle_id} className="coach-item">
      <div className="coach-say">{c.self_check.instruction}</div>
      <div className="coach-why">{c.driving_principle}</div>
      <div className="coach-tags">
        <span className="chip">{labels[c.fundamental] || c.fundamental.replace(/_/g, " ")}</span>
        <span className="src-tag">{c.self_check.label}</span>
      </div>
    </div>
  ));
}

// Incident cards (Track B, docs/UI-V3-PLAN.md): the engine already
// classifies each spin/off/near-stop AND deterministically decides which
// (if any) coaching principle explains it (report/payload.py's
// incidents_section, incidents/coaching.py) — this only renders that,
// following the same "complicated numbers behind the arrow" pattern as
// A3's methodology disclosures. Nothing here computes or guesses a cause;
// unclassified/external get no principle, no drill, and no guessed
// mechanism, exactly as the engine itself withheld one.
const INCIDENT_LABEL = {
  trail_brake_oversteer: "Trail-brake oversteer",
  lift_off_oversteer: "Lift-off oversteer",
  power_on_oversteer: "Power-on oversteer",
  understeer_off: "Understeer off",
  external: "Possible external cause",
  unclassified: "Cause not identified",
};

// Mechanism counts (Track B2): a tally by classification — counting, not
// computing (the same precedent as the existing shownCount elsewhere in
// this file). A count of past events, never a claim about the driver in
// general; the "never a trait" line sits right next to it so the tally
// can't be read as a verdict on its own.
export function IncidentMechanismCounts({ events }) {
  if (!events.length) return null;
  const counts = new Map();
  for (const e of events) {
    counts.set(e.classification, (counts.get(e.classification) || 0) + 1);
  }
  return (
    <div className="chips" style={{ marginTop: 0, marginBottom: "0.6rem" }}>
      {[...counts.entries()].map(([cls, n]) => (
        <span key={cls} className="chip num">
          {n} {INCIDENT_LABEL[cls] || cls.replace(/_/g, " ")}
        </span>
      ))}
      <span className="chip dim">events, not traits</span>
    </div>
  );
}

export function IncidentCard({ event, slug }) {
  const named = event.coaching_principle_id != null;
  const empathy = useMethodologyText(named ? `incident.empathy.${event.classification}` : null);
  const mechanism = useMethodologyText(`incident.${event.classification}`);

  return (
    <div className={`finding incident-card ${named ? "" : "suppressed"}`}>
      <div className="head">
        <span className="desc">
          {event.corner_id ? <a href={`#/corner/${slug}/${event.corner_id}`}>{event.corner_id}</a> : "this lap"}
          {" · "}{INCIDENT_LABEL[event.classification] || event.classification.replace(/_/g, " ")}
        </span>
        <span className="val">{event.confidence}</span>
      </div>
      <div className="meta">single event, not a trait</div>

      <details className="disclosure">
        <summary><span className="chev" aria-hidden="true">▸</span> What happened, and what to practise</summary>
        <div className="disclosure-body">
          {empathy && <p style={{ margin: "0 0 0.5rem" }}>{empathy}</p>}
          {mechanism && <p style={{ margin: "0 0 0.5rem" }}>{mechanism}</p>}
          {named && (event.drill || event.coaching_expression) && (
            <div className="coach-drill">
              <b>Try this:</b> {event.drill || event.coaching_expression}
            </div>
          )}
          <div className="meta num" style={{ marginTop: "0.5rem" }}>
            min <span className="num">{fmt(event.min_speed_kmh, 0)}</span> km/h ·
            peak yaw <span className="num">{fmt(event.peak_yaw_rate)}</span> rad/s ·{" "}
            <span className="dim" title={event.lap_id}>{event.lap_id.slice(0, 6)}…</span>
          </div>
          <div className="reason" style={{ marginTop: "0.3rem" }}>{event.rationale}</div>
        </div>
      </details>
    </div>
  );
}

export function LossBars({ entries, unit = "s" }) {
  const values = entries.map(([, v]) => Math.abs(v));
  const peak = Math.max(...values, 1e-9);
  return (
    <div>
      {entries.map(([key, value], i) => (
        <div key={key} className={`lossrow ${Math.abs(value) === Math.max(...values) ? "max" : ""}`}>
          <span className="k">{key}</span>
          <span className="bar"><i style={{ width: `${(Math.abs(value) / peak) * 100}%` }} /></span>
          <span className="v num">{fmt(value)}</span>
        </div>
      ))}
    </div>
  );
}
