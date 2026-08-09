import { useEffect, useState } from "react";
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

// Findings grouped exactly as the payload states them: shown (priorities),
// annotated (driver's call, measurement visible), suppressed (reason shown).
export function FindingRow({ finding, slug }) {
  const cls = finding.shown && !finding.annotation ? "" : "suppressed";
  return (
    <div className={`finding ${cls}`}>
      <div className="head">
        <span className="desc">
          <a href={`#/finding/${slug}/${encodeURIComponent(finding.finding_id)}`}>
            {finding.description}
          </a>
        </span>
        <span className="val num">
          {finding.seconds === null ? "" : `${fmt(finding.seconds)} s`}
        </span>
      </div>
      <div className="meta num">
        n={finding.n}
        {finding.spread !== null && <> · spread {fmt(finding.spread)}</>}
        {finding.source === "vs-reference" && finding.details?.reference_n != null && (
          <> · ref n={finding.details.reference_n}</>
        )}
        {finding.annotation && (
          <> · {finding.annotation.status} by you — measurement kept</>
        )}
      </div>
      {!finding.shown && <div className="reason">{finding.gate_reason}</div>}
    </div>
  );
}

export function SourceSections({ findings, slug }) {
  const sources = ["vs-self", "vs-principle", "vs-reference"];
  const labels = {
    "vs-self": "vs-self — your faster laps vs your slower laps",
    "vs-principle": "vs-principle — canonical technique checks",
    "vs-reference": "vs-reference — gap to reference (context, not recoverable time)",
  };
  return sources.map((source) => {
    const group = findings.filter((f) => f.source === source);
    if (!group.length) return null;
    const shown = group.filter((f) => f.shown && !f.annotation);
    const annotated = group.filter((f) => f.shown && f.annotation);
    const suppressed = group.filter((f) => !f.shown);
    return (
      <div key={source} className={`source-section ${source}`}>
        <p className="eyebrow"><span className="src-tag">{source}</span>{labels[source]}</p>
        <Methodology id={`source.${source}`} label="How does this source work?" />
        {shown.map((f) => <FindingRow key={f.finding_id} finding={f} slug={slug} />)}
        {!shown.length && (
          <div className="dim" style={{ fontSize: "0.8rem", padding: "0.2rem 0 0.4rem" }}>
            Nothing clears the gates yet — {suppressed.length} suppressed below, each with its reason.
          </div>
        )}
        {annotated.map((f) => <FindingRow key={f.finding_id} finding={f} slug={slug} />)}
        {suppressed.slice(0, 6).map((f) => (
          <FindingRow key={f.finding_id} finding={f} slug={slug} />
        ))}
        {suppressed.length > 6 && (
          <div className="dim" style={{ fontSize: "0.74rem", padding: "0.35rem 0 0" }}>
            + {suppressed.length - 6} more suppressed (same gates) — full list in the JSON report.
          </div>
        )}
      </div>
    );
  });
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

function CoachingTags({ item, slug }) {
  const mag = magnitudeText(item.magnitude_kind, item.magnitude);
  return (
    <div className="coach-tags">
      <span className="chip">{item.fundamental.replace(/_/g, " ")}</span>
      {item.corner_id && (
        <span className="chip">
          <a href={`#/corner/${slug}/${item.corner_id}`}>{item.corner_id}</a>
        </span>
      )}
      {item.gap_band && <span className="chip">{item.gap_band}</span>}
      {mag && <span className="chip num">{mag}</span>}
      <span className="chip num dim">n={item.n}</span>
      {item.thin_evidence && <span className="chip dim">thin evidence</span>}
    </div>
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
              <div className="coach-tags">
                <span className="chip">{head.fundamental.replace(/_/g, " ")}</span>
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

export function CoachingSelfChecks({ items }) {
  if (!items.length) return null;
  return items.map((c) => (
    <div key={c.coaching_principle_id} className="coach-item">
      <div className="coach-say">{c.self_check.instruction}</div>
      <div className="coach-why">{c.driving_principle}</div>
      <div className="coach-tags">
        <span className="chip">{c.fundamental.replace(/_/g, " ")}</span>
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

export function LossBars({ entries }) {
  const values = entries.map(([, v]) => Math.abs(v));
  const peak = Math.max(...values, 1e-9);
  return (
    <div>
      {entries.map(([key, value]) => (
        <div key={key} className={`lossrow ${Math.abs(value) === Math.max(...values) ? "max" : ""}`}>
          <span className="k">{key}</span>
          <span className="bar"><i style={{ width: `${(Math.abs(value) / peak) * 100}%` }} /></span>
          <span className="v num">{fmt(value)}</span>
        </div>
      ))}
    </div>
  );
}
