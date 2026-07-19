import React from "react";
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
