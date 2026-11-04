"use client";

import type { InvestigationDetail, PredictionResult, RealityView } from "@/lib/types";
import { Tag } from "@/components/ui";
import { EvidenceRefs } from "./evidence";

const COMPATIBILITY: Record<string, { text: string; tone: "neutral" | "ok" | "warn" | "bad" }> = {
  untested: { text: "Untested", tone: "neutral" },
  compatible: { text: "Compatible", tone: "neutral" },
  consistent: { text: "Consistent", tone: "ok" },
  corroborated: { text: "Corroborated", tone: "warn" },
  strained: { text: "Strained", tone: "warn" },
  incompatible: { text: "Excluded", tone: "bad" },
};

const OUTCOME_COLOR: Record<string, string> = {
  matched: "var(--color-fg)",
  violated: "var(--color-bad)",
  inconclusive: "var(--color-warn)",
  untested: "var(--color-mute)",
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
        <line x1="6" y1="9" x2="12" y2="9" stroke="var(--color-mute)" strokeWidth="1.5" />
      </svg>
    );
  }
  const color = OUTCOME_COLOR[prediction.outcome] ?? "var(--color-mute)";
  const dashed = prediction.outcome === "untested";
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
      <circle cx="9" cy="9" r="7.25" stroke={color} strokeWidth={prediction.hard ? 1.5 : 1} strokeDasharray={dashed ? "2.5 2.5" : undefined} />
      {prediction.expects === "positive" && <circle cx="9" cy="9" r="3" fill={color} />}
      {prediction.outcome === "violated" && <line x1="3.5" y1="14.5" x2="14.5" y2="3.5" stroke={color} strokeWidth="1.5" />}
    </svg>
  );
}

function observedText(state: string | null | undefined, value: number | null | undefined) {
  if (!state) return { text: "Not observed", color: "text-mute" };
  if (state === "unavailable") return { text: "Unavailable", color: "text-bad" };
  if (state === "partial") return { text: "Partial", color: "text-warn" };
  if (state === "zero") return { text: "None", color: "text-dim" };
  return { text: value !== undefined && value !== null ? `Yes · ${value}` : "Yes", color: "text-fg" };
}

function Legend() {
  const sample = (expects: "zero" | "positive", outcome: PredictionResult["outcome"]) =>
    ({ expects, outcome, hard: true }) as PredictionResult;
  const items: [PredictionResult, string][] = [
    [sample("positive", "matched"), "Predicts a positive result"],
    [sample("zero", "matched"), "Predicts nothing found"],
    [sample("zero", "untested"), "Not yet observed"],
    [sample("zero", "violated"), "Conflicts with observation"],
    [sample("positive", "inconclusive"), "Inconclusive"],
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-dim">
      {items.map(([prediction, text]) => (
        <span key={text} className="flex items-center gap-1.5"><PredictionGlyph prediction={prediction} /> {text}</span>
      ))}
    </div>
  );
}

export interface Observed {
  ref: string;
  state: string | null;
  value: number | null;
}

export function matrixRows(realities: RealityView[]) {
  const keys = [...new Set(realities.flatMap((r) => r.predictions.map((p) => p.observable)))];
  return keys
    .map((key) => {
      const cells = realities.map((r) => r.predictions.find((p) => p.observable === key));
      const stances = new Set(cells.map((c) => c?.expects ?? "any"));
      return { key, cells, label: cells.find(Boolean)?.label ?? key, discriminates: stances.size > 1 };
    })
    .sort((a, b) => Number(b.discriminates) - Number(a.discriminates));
}

/** Observations against each explanation's prediction. Rows that can separate them come first. */
export function PredictionMatrix({ realities, observed, tests }: { realities: RealityView[]; observed: Record<string, Observed | undefined>; tests?: Record<string, string> }) {
  const rows = matrixRows(realities);
  const hasTests = Boolean(tests);
  const columns = `minmax(200px,1.6fr) 92px repeat(${realities.length}, 54px)${hasTests ? " minmax(150px,1fr)" : ""}`;
  return (
    <div>
      <div className="overflow-x-auto">
        <div role="table" aria-label="Predictions of each explanation compared with observations" className={hasTests ? "min-w-[680px]" : "min-w-[520px]"}>
          <div role="row" className="grid items-end gap-x-3 border-b border-line py-2" style={{ gridTemplateColumns: columns }}>
            <span role="columnheader" className="label">Observation</span>
            <span role="columnheader" className="label">Observed</span>
            {realities.map((reality) => (
              <span role="columnheader" key={reality.label} className={`label text-center ${reality.compatibility === "incompatible" ? "excluded" : "text-fg"}`} title={reality.title}>{reality.label}</span>
            ))}
            {hasTests && <span role="columnheader" className="label">Test that answers it</span>}
          </div>
          {rows.map((row) => {
            const item = observed[row.key];
            const shown = observedText(item?.state, item?.value);
            return (
              <div role="row" key={row.key} className={`grid items-center gap-x-3 border-b border-line/60 py-2 ${row.discriminates ? "" : "opacity-55"}`} style={{ gridTemplateColumns: columns }}>
                <span role="cell" className="min-w-0 text-[13px]">
                  {row.label}
                  {item && <span className="mono ml-2 text-[11px] text-mute">{item.ref}</span>}
                </span>
                <span role="cell" className={`mono text-xs ${shown.color}`}>{shown.text}</span>
                {row.cells.map((cell, index) => {
                  const reality = realities[index];
                  const text = cell ? `${reality.title}: ${cell.reason} ${OUTCOME_TEXT[cell.outcome]}.` : `${reality.title} makes no prediction here.`;
                  return (
                    <span role="cell" key={reality.label} title={text} aria-label={text} className={`flex justify-center ${reality.compatibility === "incompatible" ? "excluded" : ""}`}>
                      <PredictionGlyph prediction={cell} />
                    </span>
                  );
                })}
                {hasTests && <span role="cell" className="truncate text-xs text-dim" title={tests?.[row.key]}>{tests?.[row.key] ?? "First pass"}</span>}
              </div>
            );
          })}
        </div>
      </div>
      <div className="mt-3"><Legend /></div>
    </div>
  );
}

function RealityColumn({ reality, separators }: { reality: RealityView; separators: string[] }) {
  const excluded = reality.compatibility === "incompatible";
  const compatibility = COMPATIBILITY[reality.compatibility] ?? COMPATIBILITY.untested;
  return (
    <article className={`min-w-0 py-1 ${excluded ? "excluded" : ""}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="label">Reality {reality.label}</span>
        <Tag tone={compatibility.tone}>{compatibility.text}</Tag>
      </div>
      <h4 className={`text-[17px] font-light leading-snug ${excluded ? "line-through decoration-mute" : ""}`}>{reality.title}</h4>
      <p className="mt-1.5 text-[13px] text-dim">{reality.statement}</p>
      <dl className="mt-4 space-y-2.5 text-[13px]">
        <div className="flex items-baseline gap-3">
          <dt className="w-[100px] shrink-0 text-xs text-mute">Supported by</dt>
          <dd><EvidenceRefs refs={reality.supporting} empty="Nothing yet" /></dd>
        </div>
        <div className="flex items-baseline gap-3">
          <dt className="w-[100px] shrink-0 text-xs text-mute">Contradicted by</dt>
          <dd><EvidenceRefs refs={reality.contradicting} empty="Nothing yet" /></dd>
        </div>
      </dl>
      {separators.length > 0 && (
        <p className="mt-3 text-xs text-dim"><span className="text-mute">Would show: </span>{separators.join(", ")}</p>
      )}
      <details className="mt-3 text-xs text-dim">
        <summary className="cursor-pointer transition-colors hover:text-fg">Assumptions and challenge</summary>
        <ul className="mt-2 space-y-1">
          {reality.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}
        </ul>
        {reality.challenge && <p className="mt-2 border-t border-line pt-2">{reality.challenge}</p>}
      </details>
    </article>
  );
}

export function CompetingRealities({ investigation }: { investigation: InvestigationDetail }) {
  const { realities, evidence, checks } = investigation;
  const observed = Object.fromEntries(evidence.filter((e) => e.primary).map((e) => [e.observable, { ref: e.ref, state: e.state, value: e.value }]));
  const tests = Object.fromEntries(checks.flatMap((c) => c.observables.map((o) => [o, c.title])));
  const rows = matrixRows(realities);
  const open = rows.filter((row) => row.discriminates && !observed[row.key]);
  const survivors = realities.filter((r) => r.compatibility !== "incompatible");
  const separators = (reality: RealityView) =>
    reality.predictions
      .filter((p) => p.expects === "positive" && rows.find((r) => r.key === p.observable)?.discriminates)
      .map((p) => p.label);
  return (
    <div className="space-y-8">
      <p className="text-[15px] text-dim">
        {survivors.length} of {realities.length} explanations fit everything observed so far.
        {open.length > 0 && survivors.length > 1 && ` ${open.length} observations that could separate them have not been made yet.`}
      </p>
      <div className="grid gap-x-8 gap-y-6 divide-line max-md:divide-y" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        {realities.map((reality) => <RealityColumn key={reality.label} reality={reality} separators={separators(reality)} />)}
      </div>
      <PredictionMatrix realities={realities} observed={observed} tests={tests} />
      <p className="text-xs text-mute">These are generated hypotheses, not findings. Each stays a hypothesis even when the evidence fits it.</p>
    </div>
  );
}
