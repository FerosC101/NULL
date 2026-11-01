"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { Field, Modal, Tag } from "@/components/ui";
import { useApi } from "@/lib/api";
import { utc } from "@/lib/format";
import type { EvidenceView } from "@/lib/types";

const RELIABILITY_TONE: Record<string, "ok" | "warn" | "neutral"> = { high: "ok", moderate: "neutral", low: "warn" };

interface RawRecord {
  id: number;
  source_key: string;
  ts: string;
  entity: string;
  payload: Record<string, unknown>;
}

const InspectContext = createContext<(ref: string) => void>(() => {});

export const useInspect = () => useContext(InspectContext);

function EvidenceDrawer({ item, investigationId, onClose }: { item: EvidenceView; investigationId: string; onClose: () => void }) {
  const { data, loading, error } = useApi<{ records: RawRecord[] }>(`/investigations/${investigationId}/evidence/${item.ref}`);
  return (
    <Modal open drawer width={560} onClose={onClose} label={item.ref} title={item.observable_label}>
      <p className="label mb-1">Observed</p>
      <p className="text-[15px] leading-relaxed">{item.observation}</p>
      <dl className="mt-6 grid grid-cols-2 gap-5">
        <Field label="Timestamp"><span className="mono text-xs">{utc(item.observed_at)}</span></Field>
        <Field label="Source"><span className="mono text-xs">{item.provenance.sources.join(", ")}</span></Field>
        <Field label="Reliability">
          <Tag tone={RELIABILITY_TONE[item.reliability]}>{item.reliability}</Tag>
        </Field>
        <Field label="Relevance">{item.relevance}</Field>
      </dl>
      <p className="mt-4 text-[13px] text-dim">{item.reliability_basis}</p>
      <h3 className="label mb-2 mt-7 border-t border-line pt-5">Provenance</h3>
      <dl className="space-y-3">
        <Field label="Tool"><span className="mono text-xs">{item.provenance.tool}</span></Field>
        <Field label="Method">{item.provenance.method}</Field>
        <Field label="SHA-256 of cited records">
          <span className="mono break-all text-[11px]">{item.provenance.sha256}</span>
        </Field>
      </dl>
      <h3 className="label mb-2 mt-7 border-t border-line pt-5">
        Source records ({item.provenance.record_ids.length} cited)
      </h3>
      {loading && <div className="skeleton h-24" />}
      {error && <p className="text-sm text-bad">{error}</p>}
      <div className="space-y-2">
        {data?.records.slice(0, 6).map((record) => (
          <pre key={record.id} className="mono overflow-x-auto rounded-md border border-line bg-base p-3 text-[11px] leading-relaxed text-dim">
            {`#${record.id} ${record.source_key} ${utc(record.ts)}\n${JSON.stringify(record.payload, null, 2)}`}
          </pre>
        ))}
      </div>
      {data && data.records.length > 6 && <p className="mt-2 text-xs text-mute">Showing 6 of {data.records.length} records.</p>}
    </Modal>
  );
}

/** Lets any chart, finding or explanation open the same evidence drawer. */
export function EvidenceProvider({ evidence, investigationId, children }: { evidence: EvidenceView[]; investigationId: string; children: ReactNode }) {
  const [selected, setSelected] = useState<string | null>(null);
  const item = evidence.find((e) => e.ref === selected);
  return (
    <InspectContext.Provider value={setSelected}>
      {children}
      {item && <EvidenceDrawer item={item} investigationId={investigationId} onClose={() => setSelected(null)} />}
    </InspectContext.Provider>
  );
}

export function EvidenceRef({ value, tone = "" }: { value: string; tone?: string }) {
  const inspect = useInspect();
  return (
    <button type="button" onClick={() => inspect(value)} className={`mono whitespace-nowrap text-xs underline decoration-line underline-offset-4 transition-colors hover:decoration-fg ${tone}`}>
      {value}
    </button>
  );
}

export function EvidenceRefs({ refs, empty = "None" }: { refs: string[]; empty?: string }) {
  if (!refs.length) return <span className="text-xs text-mute">{empty}</span>;
  return <span className="flex flex-wrap gap-x-2.5 gap-y-1">{refs.map((ref) => <EvidenceRef key={ref} value={ref} />)}</span>;
}

export function EvidenceTable({ evidence }: { evidence: EvidenceView[] }) {
  const [filter, setFilter] = useState("");
  const rows = useMemo(() => {
    const term = filter.toLowerCase();
    return evidence.filter((e) => !term || `${e.ref} ${e.source_key} ${e.observation}`.toLowerCase().includes(term));
  }, [evidence, filter]);

  return (
    <>
      <div className="mb-2 flex items-center justify-between gap-4">
        <input aria-label="Filter evidence" className="field max-w-xs" placeholder="Filter evidence" value={filter} onChange={(event) => setFilter(event.target.value)} />
        <span className="mono shrink-0 text-xs text-mute">{rows.length} of {evidence.length} items</span>
      </div>
      <ul className="divide-y divide-line/60 border-y border-line">
        {rows.map((item) => (
          <li key={item.ref} className="grid items-baseline gap-x-4 gap-y-0.5 py-2.5 sm:grid-cols-[72px_minmax(0,1fr)_84px_78px]">
            <EvidenceRef value={item.ref} />
            <span className="text-[13px] text-dim">{item.observation}</span>
            <span className="mono truncate text-[11px] text-mute" title={item.provenance.sources.join(", ")}>{item.source_key}</span>
            <span><Tag tone={RELIABILITY_TONE[item.reliability]}>{item.reliability}</Tag></span>
          </li>
        ))}
        {rows.length === 0 && <li className="py-4 text-[13px] text-dim">No evidence matches this filter.</li>}
      </ul>
    </>
  );
}
