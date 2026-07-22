import React, { useState } from "react";
import { fmt } from "../format.js";

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
