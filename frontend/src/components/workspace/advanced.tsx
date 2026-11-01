"use client";

import { Check, CircleDashed, X } from "lucide-react";
import type { ReactNode } from "react";
import { ChartFrame, TimeChart, timeTable, type TimePoint } from "@/components/charts";
import { duration, utc } from "@/lib/format";
import type { EventView, Exhibits, InvestigationDetail } from "@/lib/types";
import { EvidenceRef, useInspect } from "./evidence";

function Disclosure({ title, summary, open, children }: { title: string; summary?: string; open?: boolean; children: ReactNode }) {
  return (
    <details open={open} className="group border-b border-line">
      <summary className="flex cursor-pointer items-baseline justify-between gap-4 py-3 text-[15px] transition-colors hover:text-fg">
        <span>{title}</span>
        {summary && <span className="text-xs text-mute">{summary}</span>}
      </summary>
      <div className="pb-5">{children}</div>
    </details>
  );
}

function EventMark({ event }: { event: EventView }) {
  const common = "flex size-[18px] shrink-0 items-center justify-center rounded-full border bg-base";
  if (event.planned) return <span className={`${common} border-dashed border-mute`}><span className="sr-only">Planned</span></span>;
  if (event.tone === "bad") return <span className={`${common} border-bad text-bad`}><X size={10} strokeWidth={3} aria-hidden /></span>;
  if (event.tone === "ok") return <span className={`${common} border-ok text-ok`}><Check size={10} strokeWidth={3} aria-hidden /></span>;
  return <span className={`${common} border-fg`}><Check size={10} strokeWidth={3} aria-hidden /></span>;
}

export function InvestigationTimeline({ events }: { events: EventView[] }) {
  return (
    <ol className="relative">
      <span aria-hidden className="absolute bottom-3 left-[8.5px] top-3 w-px bg-line" />
      {events.map((event, index) => (
        <li key={`${event.label}-${index}`} className="relative flex gap-3 pb-3.5 last:pb-0">
          <EventMark event={event} />
          <div className="min-w-0">
            <p className={`text-[13px] leading-[18px] ${event.planned ? "text-mute" : ""}`}>{event.label}</p>
            <p className="mono text-[11px] text-mute">{event.planned ? "Planned" : utc(event.at)}</p>
            {event.detail && <p className="mt-0.5 line-clamp-2 text-xs text-dim">{event.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function AdvancedAnalysis({ investigation, exhibits }: { investigation: InvestigationDetail; exhibits: Exhibits | null }) {
  const inspect = useInspect();
  const signins = exhibits?.signins;
  const points: TimePoint[] = signins?.points.map((p) => ({ iso: p.ts, value: p.failures, expected: p.expected, flagged: p.flagged })) ?? [];
  const format = (value: number) => value.toLocaleString();
  const tools = investigation.tool_executions;
  const failed = tools.filter((t) => t.status === "failed").length;
  const records = tools.reduce((total, t) => total + t.records_read, 0);
  const primary = investigation.evidence.filter((e) => e.primary);
  const compiled = investigation.compiled_claim;
  return (
    <section aria-labelledby="advanced-heading">
      <h2 id="advanced-heading" className="label mb-1">Advanced analysis</h2>
      <div className="border-t border-line">
        <Disclosure title="Investigation timeline" summary={`${investigation.events.filter((e) => !e.planned).length} recorded`}>
          <InvestigationTimeline events={investigation.events} />
        </Disclosure>
        <Disclosure title="Statistical analysis" summary={signins ? `${signins.flagged_hours} of ${signins.points.length} hours flagged` : undefined}>
          {signins ? (
            <ChartFrame
              title="Failed sign-ins per hour"
              interpretation={`${signins.flagged_hours} of ${signins.points.length} hours exceed the same hour-of-day baseline at FDR 0.01. Poisson tail test, Benjamini-Hochberg corrected.`}
              period={`${utc(investigation.scope.window_start)} to ${utc(investigation.scope.window_end)}`}
              source={exhibits?.refs.signins ? <span className="flex items-center gap-1.5">Source <EvidenceRef value={exhibits.refs.signins} /></span> : undefined}
              table={timeTable(points, "Failures", "Baseline", format)}
            >
              <TimeChart
                bars
                points={points}
                unit="Failed sign-ins per hour"
                observedName="Failed sign-ins"
                expectedName="Baseline for that hour"
                formatValue={format}
                onSelect={exhibits?.refs.signins ? () => inspect(exhibits.refs.signins!) : undefined}
              />
            </ChartFrame>
          ) : (
            <p className="text-sm text-dim">Authentication records weren&apos;t readable, so no statistics are available.</p>
          )}
        </Disclosure>
        <Disclosure title="Assumptions" summary={`${investigation.assumptions.length} tracked`}>
          <ul className="space-y-2.5 text-[13px]">
            {investigation.assumptions.map((assumption) => (
              <li key={assumption.key}>
                <span>{assumption.text}</span>
                <span className="mono ml-2 text-[11px] text-mute">{assumption.status}</span>
                {assumption.basis && <span className="block text-xs text-dim">{assumption.basis}</span>}
              </li>
            ))}
          </ul>
        </Disclosure>
        <Disclosure title="Identifiability conditions" summary={compiled.kind?.replaceAll("_", " ")}>
          <p className="text-[13px] text-dim">{compiled.interpretation || "This claim has no compiled interpretation."}</p>
          <p className="mt-2 text-xs text-mute">Compiled by {compiled.compiler || "the rule-based compiler"}. The claim can be established only where the evidence could have shown the opposite, which is why coverage is measured before any conclusion.</p>
        </Disclosure>
        <Disclosure title="Counterfactual construction" summary={`${investigation.realities.length} explanations`}>
          <ul className="space-y-4">
            {investigation.realities.map((reality) => (
              <li key={reality.label}>
                <p className="text-[13px]">Reality {reality.label}: {reality.title} <span className="mono text-[11px] text-mute">origin {reality.origin}</span></p>
                <ul className="mt-1 space-y-0.5 text-xs text-dim">
                  {reality.predictions.filter((p) => p.expects !== "any").map((p) => (
                    <li key={p.observable}>{p.label}: expects {p.expects === "zero" ? "nothing" : "a positive result"}, likelihood {p.p_positive.toFixed(2)}{p.hard ? ", required" : ""}. {p.reason}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Disclosure>
        <Disclosure title="Evidence provenance" summary={`${primary.length} primary items`}>
          <ul className="space-y-1.5">
            {primary.map((item) => (
              <li key={item.ref} className="grid items-baseline gap-x-3 text-xs sm:grid-cols-[72px_170px_minmax(0,1fr)]">
                <EvidenceRef value={item.ref} />
                <span className="mono truncate text-dim">{item.provenance.tool}</span>
                <span className="mono truncate text-mute">{item.provenance.sha256}</span>
              </li>
            ))}
          </ul>
        </Disclosure>
        <Disclosure title="Execution logs" summary={`${tools.length} calls, ${records.toLocaleString()} records${failed ? `, ${failed} failed` : ""}`}>
          <ul className="space-y-2">
            {tools.map((execution) => (
              <li key={execution.id} className="text-xs">
                <span className="flex items-baseline justify-between gap-2">
                  <span className={`mono truncate ${execution.status === "failed" ? "text-bad" : "text-dim"}`}>{execution.tool}</span>
                  <span className="mono shrink-0 text-mute">{duration(execution.started_at, execution.finished_at)}</span>
                </span>
                <span className="text-mute">{execution.role}{execution.records_read > 0 && ` · ${execution.records_read.toLocaleString()} records`}</span>
                {execution.error && <span className="mt-0.5 block text-bad">{execution.error}</span>}
              </li>
            ))}
          </ul>
        </Disclosure>
        <Disclosure title="Model reasoning and diagnostics" summary={investigation.reasoning_mode}>
          <p className="flex items-start gap-2 text-[13px] text-dim">
            <CircleDashed size={13} className="mt-1 shrink-0" aria-hidden />
            {investigation.reasoning_note || "Not started"}
          </p>
          {investigation.explorer_notes.length > 0 && (
            <ul className="mt-3 space-y-2 text-xs text-dim">
              {investigation.explorer_notes.map((note) => (
                <li key={note.text}>
                  {note.text}
                  {note.evidence_refs.length > 0 && <span className="mono ml-1 text-[11px] text-mute">{note.evidence_refs.join(" ")}</span>}
                </li>
              ))}
            </ul>
          )}
        </Disclosure>
      </div>
    </section>
  );
}
