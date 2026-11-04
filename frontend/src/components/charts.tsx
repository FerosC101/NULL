"use client";

import { Check, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { clock, utc } from "@/lib/format";
import type { CoverageMatrixData, HostCoverageData, MatrixCell, MatrixRow } from "@/lib/types";

/** One tick per host, so a small gap stays visible instead of rounding away in a percentage. */
export function HostTicks({ total, flagged, label }: { total: number; flagged: string[]; label: string }) {
  const healthy = Math.max(total - flagged.length, 0);
  return (
    <div
      role="img"
      aria-label={`${label}: ${healthy} of ${total} hosts reporting. Not reporting: ${flagged.join(", ") || "none"}.`}
      className="flex h-5 items-stretch gap-px"
    >
      {Array.from({ length: healthy }, (_, index) => (
        <span key={index} className="min-w-px flex-1 bg-dim/70" />
      ))}
      {flagged.map((host) => (
        <span key={host} title={`${host}: no reporting agent`} className="min-w-px flex-1 bg-warn" />
      ))}
    </div>
  );
}

export interface Segment {
  label: string;
  value: number;
  /** Tailwind background class. Status colors are used only where the segment means that state. */
  color: string;
}

export function SegmentBar({ segments, label }: { segments: Segment[]; label: string }) {
  const present = segments.filter((s) => s.value > 0);
  const total = present.reduce((sum, s) => sum + s.value, 0);
  const description = present.map((s) => `${s.value} ${s.label}`).join(", ");
  return (
    <div>
      <div role="img" aria-label={`${label}: ${description || "none"}`} className="flex h-2 gap-0.5">
        {total === 0 && <span className="flex-1 rounded-[1px] bg-raised" />}
        {present.map((segment) => (
          <span
            key={segment.label}
            title={`${segment.value} ${segment.label}`}
            className={`rounded-[1px] ${segment.color}`}
            style={{ flexGrow: segment.value, flexBasis: 0 }}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-dim">
        {present.map((segment) => (
          <li key={segment.label} className="flex items-center gap-1.5">
            <span aria-hidden className={`size-1.5 rounded-[1px] ${segment.color}`} />
            <span className="mono">{segment.value}</span> {segment.label}
          </li>
        ))}
        {total === 0 && <li className="text-mute">Nothing recorded yet</li>}
      </ul>
    </div>
  );
}

/** A chart's standing furniture: what it shows, what it means, the period, and a way into the data. */
export function ChartFrame({
  title,
  interpretation,
  period,
  source,
  table,
  children,
}: {
  title: string;
  interpretation?: ReactNode;
  period?: string;
  source?: ReactNode;
  table?: ReactNode;
  children: ReactNode;
}) {
  return (
    <figure>
      <figcaption className="mb-3">
        <h3 className="text-[15px] leading-snug">{title}</h3>
        {interpretation && <p className="mt-0.5 text-[13px] text-dim">{interpretation}</p>}
      </figcaption>
      {children}
      {(period || source || table) && (
        <div className="mt-2.5 flex flex-wrap items-baseline justify-between gap-x-5 gap-y-1 text-xs text-mute">
          {period && <span className="mono text-[11px]">{period}</span>}
          {source}
        </div>
      )}
      {table && (
        <details className="no-print mt-1.5 text-xs text-dim">
          <summary className="cursor-pointer transition-colors hover:text-fg">View data as a table</summary>
          <div className="mt-2 max-h-72 overflow-auto rounded-md border border-line">{table}</div>
        </details>
      )}
    </figure>
  );
}

function DataTable({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <table className="w-full text-left text-xs">
      <thead>
        <tr className="border-b border-line bg-surface">
          {head.map((heading) => <th key={heading} scope="col" className="label px-3 py-1.5 font-normal">{heading}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index} className="border-b border-line/50 last:border-b-0">
            {row.map((cell, cellIndex) => <td key={cellIndex} className="px-3 py-1.5 text-dim">{cell}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const CLOSED_ROW: Record<string, string> = {
  disconnected: "Disconnected, not read",
  not_selected: "Not selected for this investigation",
  restricted: "Restricted. Not read until an approved test reads it",
  empty: "This dataset has no records from this source",
};

const CELL_STYLE = { records: "bg-dim/70", none: "bg-raised", gap: "bg-bad" };
const CELL_WORD = { records: "Records present", none: "No records in this period", gap: "Collection gap" };

/** Sources against hours. Gaps are visible at a glance, and an unread source never looks like an empty one. */
export function CoverageMatrix({ matrix, onInspect }: { matrix: CoverageMatrixData; onInspect?: (ref: string) => void }) {
  const [reading, setReading] = useState<string | null>(null);
  const describe = (row: MatrixRow, cell: MatrixCell) =>
    `${row.label}, ${utc(cell.start)}${cell.hours > 1 ? ` for ${cell.hours} hours` : ""}: ${cell.count.toLocaleString()} records. ${CELL_WORD[cell.state]}.`;
  return (
    <div>
      <div className="min-w-0">
        <div aria-hidden className="mb-1 hidden gap-3 sm:grid sm:grid-cols-[176px_minmax(0,1fr)_56px]">
          <span />
          <span className="flex">
            {matrix.hours.map((hour, index) => (
              <span key={hour} className="mono min-w-0 flex-1 overflow-visible whitespace-nowrap text-[10px] text-mute">
                {index % 6 === 0 ? clock(hour) : ""}
              </span>
            ))}
          </span>
          <span className="label text-right">Records</span>
        </div>
        <ul>
          {matrix.rows.map((row) => (
            <li key={row.key} className="grid items-center gap-x-3 py-[3px] sm:grid-cols-[176px_minmax(0,1fr)_56px]">
              <span className="truncate text-xs text-dim" title={row.label}>{row.label}</span>
              {row.state === "readable" ? (
                <>
                  <span className="flex h-4 gap-px">
                    {row.cells.map((cell) => {
                      const text = describe(row, cell);
                      const notable = cell.state === "gap";
                      return (
                        <button
                          key={cell.start}
                          type="button"
                          aria-label={text}
                          tabIndex={notable ? 0 : -1}
                          style={{ flexGrow: cell.hours, flexBasis: 0 }}
                          onMouseEnter={() => setReading(text)}
                          onFocus={() => setReading(text)}
                          onClick={() => row.evidence_ref && onInspect?.(row.evidence_ref)}
                          className={`min-w-0 rounded-[1px] transition-opacity hover:opacity-70 ${CELL_STYLE[cell.state]}`}
                        />
                      );
                    })}
                  </span>
                  <span className="mono hidden text-right text-[11px] text-mute sm:block">{row.records?.toLocaleString()}</span>
                </>
              ) : (
                <span className="flex h-4 items-center rounded-[1px] border border-dashed border-line px-2 text-[11px] text-mute sm:col-span-2">
                  {CLOSED_ROW[row.state] ?? row.state}
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-dim">
        {(["records", "none", "gap"] as const).map((state) => (
          <span key={state} className="flex items-center gap-1.5">
            <span aria-hidden className={`size-2.5 rounded-[1px] ${CELL_STYLE[state]}`} /> {CELL_WORD[state]}
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-[1px] border border-dashed border-line" /> Not read
        </span>
      </div>
      <p aria-live="polite" className="no-print mt-1.5 min-h-[18px] text-xs text-dim">{reading}</p>
    </div>
  );
}

export function matrixTable(matrix: CoverageMatrixData) {
  return (
    <DataTable
      head={["Source", "State", "Records", "Periods with records", "Gap hours"]}
      rows={matrix.rows.map((row) => [
        row.label,
        row.state,
        row.records?.toLocaleString() ?? "Not read",
        row.state === "readable" ? `${row.cells.filter((c) => c.count > 0).length} of ${row.cells.length}` : "Not read",
        row.cells.filter((c) => c.state === "gap").reduce((sum, c) => sum + c.hours, 0),
      ])}
    />
  );
}

function Channel({ value, seen = "Seen" }: { value: boolean | null; seen?: string }) {
  if (value === null) return <span className="text-mute">Not read</span>;
  return value ? (
    <span className="flex items-center gap-1.5 text-dim"><Check size={12} aria-hidden /> {seen}</span>
  ) : (
    <span className="flex items-center gap-1.5 text-bad"><X size={12} aria-hidden /> None</span>
  );
}

/** Which channels can still see each host that EDR cannot. */
export function HostCoverage({ data }: { data: HostCoverageData }) {
  if (data.unavailable) return <p className="text-[13px] text-dim">Host coverage couldn&apos;t be read. {data.unavailable}.</p>;
  const hosts = data.unmonitored ?? [];
  return (
    <div>
      <ul className="space-y-2.5">
        {data.by_class?.map((row) => (
          <li key={row.asset_class} className="grid items-center gap-x-3 sm:grid-cols-[120px_minmax(0,1fr)_64px]">
            <span className="text-xs text-dim">{row.label}</span>
            <HostTicks total={row.hosts} flagged={row.uncovered} label={row.label} />
            <span className="mono text-[11px] text-mute sm:text-right">{row.reporting} / {row.hosts}</span>
          </li>
        ))}
      </ul>
      {hosts.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-[13px]">
            <caption className="sr-only">Evidence channels for hosts without a reporting agent</caption>
            <thead>
              <tr className="border-b border-line">
                {["Host", "EDR agent", "Network", "Independent logs"].map((heading) => (
                  <th key={heading} scope="col" className="label py-1.5 pr-4 font-normal">{heading}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {hosts.map((host) => (
                <tr key={host.hostname} className="border-b border-line/50 last:border-b-0">
                  <th scope="row" className="mono py-1.5 pr-4 text-xs font-normal">{host.hostname}</th>
                  <td className="py-1.5 pr-4 text-dim">{host.edr === "never_enrolled" ? "Never enrolled" : "Enrolled, silent"}</td>
                  <td className="py-1.5 pr-4"><Channel value={host.network} /></td>
                  <td className="py-1.5"><Channel value={host.independent_logs} seen="Forwarding" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(720);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

function ceiling(value: number) {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  return ([1, 2, 2.5, 5, 10].find((step) => value <= step * power) ?? 10) * power;
}

export interface TimePoint {
  iso: string;
  value: number | null;
  expected: number | null;
  flagged?: boolean;
}

/** One measure on one axis, hour by hour, with what was expected dashed behind it. */
export function TimeChart({
  points,
  unit,
  observedName,
  expectedName,
  bars,
  scale = 1,
  events = [],
  formatValue,
  onSelect,
}: {
  points: TimePoint[];
  unit: string;
  observedName: string;
  expectedName: string;
  bars?: boolean;
  scale?: number;
  events?: { ts: string; label: string }[];
  formatValue: (value: number) => string;
  onSelect?: () => void;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const height = 190;
  const margin = { left: 42, right: 6, top: 8, bottom: 20 };
  const plotW = Math.max(width - margin.left - margin.right, 10);
  const plotH = height - margin.top - margin.bottom;
  const known = points.flatMap((p) => [p.value, p.expected]).filter((v): v is number => v !== null).map((v) => v / scale);
  const top = ceiling(Math.max(...known, 0));
  const step = plotW / Math.max(points.length, 1);
  const x = (index: number) => margin.left + (index + 0.5) * step;
  const y = (value: number) => margin.top + plotH - (value / scale / top) * plotH;
  const path = (key: "value" | "expected") => {
    const drawn = points.map((p, i) => (p[key] === null ? null : `${x(i).toFixed(1)},${y(p[key]!).toFixed(1)}`)).filter(Boolean);
    return drawn.length ? `M${drawn.join("L")}` : "";
  };
  const hourIndex = (iso: string) => points.findIndex((p) => p.iso.slice(0, 13) === new Date(iso).toISOString().slice(0, 13));
  const current = active === null ? null : points[active];
  const labelEvery = width < 460 ? 6 : 3;

  return (
    <div>
      <div
        ref={ref}
        role="group"
        tabIndex={0}
        aria-label={`${unit}, hourly. Use the arrow keys to read each hour.`}
        className="relative"
        onKeyDown={(event) => {
          if (event.key === "ArrowRight") setActive((a) => Math.min((a ?? -1) + 1, points.length - 1));
          if (event.key === "ArrowLeft") setActive((a) => Math.max((a ?? 1) - 1, 0));
          if (event.key === "Enter") onSelect?.();
        }}
        onBlur={() => setActive(null)}
      >
        <svg width={width} height={height} className="block" aria-hidden>
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
            const tickY = margin.top + plotH * (1 - tick);
            return (
              <g key={tick}>
                <line x1={margin.left} x2={width - margin.right} y1={tickY} y2={tickY} className={tick === 0 ? "stroke-mute" : "stroke-raised"} strokeWidth="1" />
                <text x={margin.left - 7} y={tickY + 3} textAnchor="end" className="fill-mute font-mono text-[10px]">{Number((top * tick).toFixed(2))}</text>
              </g>
            );
          })}
          {points.map((point, index) => index % labelEvery === 0 && (
            <text key={point.iso} x={x(index)} y={height - 5} textAnchor="middle" className="fill-mute font-mono text-[10px]">{clock(point.iso)}</text>
          ))}
          {bars && points.map((point, index) => point.value !== null && point.value > 0 && (
            <rect
              key={point.iso}
              x={x(index) - Math.max(step - 2, 1) / 2}
              y={y(point.value)}
              width={Math.max(step - 2, 1)}
              height={margin.top + plotH - y(point.value)}
              rx="1"
              className={point.flagged ? "fill-bad" : "fill-dim/70"}
            />
          ))}
          <path d={path("expected")} fill="none" strokeWidth="1.25" strokeDasharray="4 3" className="stroke-dim" />
          {!bars && <path d={path("value")} fill="none" strokeWidth="2" strokeLinejoin="round" className="stroke-fg" />}
          {events.map((event) => {
            const index = hourIndex(event.ts);
            return index >= 0 && (
              <line key={event.ts} x1={x(index)} x2={x(index)} y1={margin.top} y2={margin.top + plotH} strokeWidth="1" className="stroke-bad" />
            );
          })}
          {active !== null && <line x1={x(active)} x2={x(active)} y1={margin.top} y2={margin.top + plotH} strokeWidth="1" className="stroke-mute" />}
          {active !== null && !bars && current?.value !== null && current?.value !== undefined && (
            <circle cx={x(active)} cy={y(current.value)} r="4" strokeWidth="2" className="fill-fg stroke-base" />
          )}
          <rect
            x={margin.left}
            y={margin.top}
            width={plotW}
            height={plotH}
            fill="transparent"
            className={onSelect ? "cursor-pointer" : undefined}
            onClick={onSelect}
            onMouseMove={(event) => {
              const left = event.currentTarget.getBoundingClientRect().left;
              setActive(Math.min(Math.max(Math.floor((event.clientX - left) / step), 0), points.length - 1));
            }}
            onMouseLeave={() => setActive(null)}
          />
        </svg>
        {current && (
          <div
            aria-live="polite"
            className="pointer-events-none absolute top-1 z-10 w-max max-w-56 rounded-md border border-line bg-raised px-2.5 py-1.5 text-xs"
            style={active! > points.length / 2 ? { right: width - x(active!) + 8 } : { left: x(active!) + 8 }}
          >
            <p className="mono text-[11px] text-dim">{utc(current.iso)}</p>
            <p>{observedName}: <span className="mono">{current.value === null ? "No record" : formatValue(current.value)}</span></p>
            <p className="text-dim">{expectedName}: <span className="mono">{current.expected === null ? "No baseline" : formatValue(current.expected)}</span></p>
            {current.flagged && <p className="text-bad">Exceeds the baseline</p>}
            {events.filter((e) => hourIndex(e.ts) === active).map((e) => <p key={e.ts} className="text-bad">{e.label}</p>)}
          </div>
        )}
      </div>
      <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-dim">
        <li className="flex items-center gap-1.5">
          {bars ? <span aria-hidden className="size-2.5 rounded-[1px] bg-dim/70" /> : <span aria-hidden className="h-0.5 w-4 bg-fg" />}
          {observedName}
        </li>
        <li className="flex items-center gap-1.5">
          <svg width="16" height="3" aria-hidden><line x1="0" x2="16" y1="1.5" y2="1.5" strokeWidth="1.25" strokeDasharray="4 3" className="stroke-dim" /></svg>
          {expectedName}
        </li>
        {events.length > 0 && <li className="flex items-center gap-1.5"><span aria-hidden className="h-3 w-px bg-bad" /> {events[0].label}</li>}
        <li className="text-mute">{unit}</li>
      </ul>
    </div>
  );
}

export function timeTable(points: TimePoint[], observed: string, expected: string, formatValue: (value: number) => string) {
  return (
    <DataTable
      head={["Hour", observed, expected]}
      rows={points.map((p) => [
        utc(p.iso),
        p.value === null ? "No record" : formatValue(p.value),
        p.expected === null ? "No baseline" : formatValue(p.expected),
      ])}
    />
  );
}

export interface PipelineStage {
  key: string;
  label: string;
  items: { ref: string; title: string }[];
  mark: string;
}

/** One square per action, so a single stuck item stays visible. Selecting a stage filters the list below. */
export function ActionPipeline({ stages, active, onSelect }: { stages: PipelineStage[]; active: string | null; onSelect: (key: string | null) => void }) {
  return (
    <ol className="grid grid-cols-2 gap-px bg-line sm:grid-cols-3 lg:grid-cols-6">
      {stages.map((stage) => {
        const on = active === stage.key;
        return (
          <li key={stage.key} className="bg-base">
            <button
              type="button"
              aria-pressed={on}
              onClick={() => onSelect(on ? null : stage.key)}
              className={`block h-full w-full px-3.5 py-3 text-left transition-colors ${on ? "bg-raised" : "hover:bg-surface"}`}
            >
              <span className="mono block text-[26px] font-light leading-none">{stage.items.length}</span>
              <span className="mt-1.5 block text-xs text-dim">{stage.label}</span>
              <span aria-hidden className="mt-2 flex min-h-2.5 flex-wrap gap-1">
                {stage.items.map((item) => <span key={item.ref} title={`${item.ref}: ${item.title}`} className={`size-2.5 rounded-[1px] ${stage.mark}`} />)}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/** Verification history in order, so a fix that passed and then regressed is visible as a sequence. */
export function RunStrip({ runs }: { runs: { id: string; passed: boolean; recurrence: boolean; created_at: string; summary: string }[] }) {
  const ordered = [...runs].sort((a, b) => a.created_at.localeCompare(b.created_at));
  if (!ordered.length) return <span className="text-xs text-mute">No runs yet</span>;
  return (
    <ol aria-label={`${ordered.length} verification runs, oldest first`} className="flex items-center gap-1">
      {ordered.map((run) => {
        const word = run.passed ? "Passed" : run.recurrence ? "Recurrence" : "Failed";
        return (
          <li key={run.id} title={`${utc(run.created_at)}: ${run.summary}`} className={`flex size-5 items-center justify-center rounded-[2px] border border-line ${run.passed ? "text-ok" : "text-bad"}`}>
            {run.passed ? <Check size={11} strokeWidth={2.5} aria-hidden /> : run.recurrence ? <RotateCcw size={11} strokeWidth={2.5} aria-hidden /> : <X size={11} strokeWidth={2.5} aria-hidden />}
            <span className="sr-only">{word}, {utc(run.created_at)}</span>
          </li>
        );
      })}
    </ol>
  );
}
