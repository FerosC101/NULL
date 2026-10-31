"use client";

import type { InvestigationDetail, PredictionResult, RealityView } from "@/lib/types";
import { Tag } from "@/components/ui";

const COMPATIBILITY: Record<string, { text: string; tone: "neutral" | "ok" | "warn" | "bad" }> = {
  untested: { text: "Untested", tone: "neutral" },
  compatible: { text: "Compatible", tone: "neutral" },
  consistent: { text: "Consistent", tone: "ok" },
  corroborated: { text: "Corroborated", tone: "warn" },
  strained: { text: "Strained", tone: "warn" },
  incompatible: { text: "Excluded", tone: "bad" },
};

const OUTCOME_COLOR: Record<string, string> = {
  matched: "#FFFFFF",
  violated: "#D46B6B",
  inconclusive: "#D6A85B",
  untested: "#6B6B6B",
};

const OUTCOME_TEXT: Record<string, string> = {
  matched: "Observation matched",
  violated: "Observation conflicts",
  inconclusive: "Inconclusive for part of the scope",
  untested: "Not yet observed",
  indifferent: "This reality predicts nothing here",
};

/** A filled centre means the reality predicts something will be seen. An empty disc predicts nothing seen. */
function PredictionGlyph({ prediction }: { prediction?: PredictionResult }) {
  if (!prediction) return <span className="text-mute">·</span>;
  if (prediction.expects === "any") {
    return (
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
        <line x1="6" y1="9" x2="12" y2="9" stroke="#6B6B6B" strokeWidth="1.5" />
      </svg>
    );
  }
  const color = OUTCOME_COLOR[prediction.outcome] ?? "#6B6B6B";
  const dashed = prediction.outcome === "untested";
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
      <circle cx="9" cy="9" r="7.25" stroke={color} strokeWidth={prediction.hard ? 1.5 : 1} strokeDasharray={dashed ? "2.5 2.5" : undefined} />
      {prediction.expects === "positive" && <circle cx="9" cy="9" r="3" fill={color} />}
      {prediction.outcome === "violated" && <line x1="3.5" y1="14.5" x2="14.5" y2="3.5" stroke={color} strokeWidth="1.5" />}
    </svg>
  );
}

function observedText(state: string | undefined, value: number | undefined) {
  if (!state) return { text: "Not observed", color: "text-mute" };
  if (state === "unavailable") return { text: "Unavailable", color: "text-bad" };
  if (state === "partial") return { text: "Partial", color: "text-warn" };
  if (state === "zero") return { text: "None", color: "text-dim" };
  return { text: value !== undefined ? `Yes · ${value}` : "Yes", color: "text-fg" };
}

function Legend() {
  const sample = (expects: "zero" | "positive", outcome: PredictionResult["outcome"]) =>
    ({ expects, outcome, hard: true }) as PredictionResult;
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-dim">
      <span className="flex items-center gap-1.5">
        <PredictionGlyph prediction={sample("positive", "matched")} /> Predicts a positive result
      </span>
      <span className="flex items-center gap-1.5">
        <PredictionGlyph prediction={sample("zero", "matched")} /> Predicts nothing found
      </span>
      <span className="flex items-center gap-1.5">
        <PredictionGlyph prediction={sample("zero", "untested")} /> Not yet observed
      </span>
      <span className="flex items-center gap-1.5">
        <PredictionGlyph prediction={sample("zero", "violated")} /> Conflicts with observation
      </span>
      <span className="flex items-center gap-1.5">
        <PredictionGlyph prediction={sample("positive", "inconclusive")} /> Inconclusive
      </span>
    </div>
  );
}

function RealityDetail({ reality }: { reality: RealityView }) {
  const excluded = reality.compatibility === "incompatible";
  const compatibility = COMPATIBILITY[reality.compatibility] ?? COMPATIBILITY.untested;
  return (
    <article className={`min-w-0 p-5 ${excluded ? "excluded" : ""}`}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="label">Reality {reality.label}</span>
        <Tag tone={compatibility.tone}>{compatibility.text}</Tag>
      </div>
      <h4 className={`text-[15px] leading-snug ${excluded ? "line-through decoration-mute" : ""}`}>{reality.title}</h4>
      <p className="mt-1.5 text-[13px] text-dim">{reality.statement}</p>
      <dl className="mt-4 space-y-3 text-[13px]">
        <div>
          <dt className="label mb-1">Assumes</dt>
          {reality.assumptions.map((assumption) => (
            <dd key={assumption} className="text-dim">{assumption}</dd>
          ))}
        </div>
        <div>
          <dt className="label mb-1">Supporting</dt>
          <dd className="mono text-xs text-dim">{reality.supporting.join("  ") || "None yet"}</dd>
        </div>
        <div>
          <dt className="label mb-1">Contradicting</dt>
          <dd className={`mono text-xs ${reality.contradicting.length ? "text-bad" : "text-dim"}`}>
            {reality.contradicting.join("  ") || "None yet"}
          </dd>
        </div>
        {reality.challenge && (
          <div>
            <dt className="label mb-1">Challenger</dt>
            <dd className="text-dim">{reality.challenge}</dd>
          </div>
        )}
      </dl>
    </article>
  );
}

export function CompetingRealities({ investigation }: { investigation: InvestigationDetail }) {
  const { realities, evidence } = investigation;
  const observableKeys = [...new Set(realities.flatMap((r) => r.predictions.map((p) => p.observable)))];
  const stateByKey = new Map(evidence.filter((e) => e.primary).map((e) => [e.observable, e]));
  const rows = observableKeys
    .map((key) => {
      const cells = realities.map((r) => r.predictions.find((p) => p.observable === key));
      const expected = new Set(cells.map((c) => c?.expects ?? "any").filter((e) => e !== "any"));
      const label = cells.find(Boolean)?.label ?? key;
      const anyStance = cells.some((c) => c && c.expects !== "any");
      const discriminates = expected.size > 1 || (expected.size === 1 && cells.some((c) => !c || c.expects === "any"));
      return { key, cells, label, discriminates, anyStance };
    })
    .sort((a, b) => Number(b.discriminates) - Number(a.discriminates));
  const columns = `minmax(220px,1.7fr) 96px repeat(${realities.length}, minmax(64px,0.6fr))`;

  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="overflow-x-auto">
        <div role="table" aria-label="Predictions of each reality compared with observations" className="min-w-[560px]">
          <div role="row" className="grid items-end gap-x-3 border-b border-line bg-surface px-5 py-2.5" style={{ gridTemplateColumns: columns }}>
            <span role="columnheader" className="label">What each reality predicts</span>
            <span role="columnheader" className="label">Observed</span>
            {realities.map((reality) => (
              <span role="columnheader" key={reality.label} className={`label text-center ${reality.compatibility === "incompatible" ? "excluded" : "text-fg"}`} title={reality.title}>
                {reality.label}
              </span>
            ))}
          </div>
          {rows.map((row) => {
            const observed = stateByKey.get(row.key);
            const shown = observedText(observed?.state ?? undefined, observed?.value ?? undefined);
            return (
              <div
                role="row"
                key={row.key}
                className={`grid items-center gap-x-3 border-b border-line/60 px-5 py-2 last:border-b-0 ${row.discriminates ? "" : "opacity-55"}`}
                style={{ gridTemplateColumns: columns }}
              >
                <span role="cell" className="min-w-0 text-[13px]">
                  {row.label}
                  {observed && <span className="mono ml-2 text-[11px] text-mute">{observed.ref}</span>}
                </span>
                <span role="cell" className={`mono text-xs ${shown.color}`}>{shown.text}</span>
                {row.cells.map((cell, index) => {
                  const reality = realities[index];
                  const text = cell
                    ? `${reality.title}: ${cell.reason} ${OUTCOME_TEXT[cell.outcome]}.`
                    : `${reality.title} makes no prediction here.`;
                  return (
                    <span role="cell" key={reality.label} title={text} aria-label={text} className={`flex justify-center ${reality.compatibility === "incompatible" ? "excluded" : ""}`}>
                      <PredictionGlyph prediction={cell} />
                    </span>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
      <div className="border-t border-line px-5 py-3">
        <Legend />
        <p className="mt-2 text-xs text-dim">
          Rows where realities agree are dimmed. They can&apos;t separate the realities, however much evidence fills them.
        </p>
      </div>
      <div className="grid divide-line border-t border-line max-md:divide-y md:divide-x" style={{ gridTemplateColumns: `repeat(auto-fit, minmax(240px, 1fr))` }}>
        {realities.map((reality) => (
          <RealityDetail key={reality.label} reality={reality} />
        ))}
      </div>
      <p className="border-t border-line bg-surface px-5 py-2.5 text-xs text-dim">
        Realities are generated hypotheses, not findings. Each stays a hypothesis even when the evidence fits it.
      </p>
    </div>
  );
}
