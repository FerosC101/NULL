"use client";

import { useMemo, useState } from "react";
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
            {`#${record.id} ${record.source_key} ${record.ts}\n${JSON.stringify(record.payload, null, 2)}`}
          </pre>
        ))}
      </div>
      {data && data.records.length > 6 && <p className="mt-2 text-xs text-mute">Showing 6 of {data.records.length} records.</p>}
    </Modal>
  );
}

export function EvidenceTable({ evidence, investigationId }: { evidence: EvidenceView[]; investigationId: string }) {
  const [selected, setSelected] = useState<EvidenceView | null>(null);
  const [filter, setFilter] = useState("");
  const rows = useMemo(() => {
    const term = filter.toLowerCase();
    return evidence.filter((e) => !term || `${e.ref} ${e.source_key} ${e.observation}`.toLowerCase().includes(term));
  }, [evidence, filter]);

  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-4">
        <input
          aria-label="Filter evidence"
          className="field max-w-xs"
          placeholder="Filter evidence"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
        <span className="mono text-xs text-mute">{rows.length} of {evidence.length} items</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[920px] table-fixed text-left text-[13px]">
          <colgroup>
            <col className="w-[92px]" />
            <col className="w-[84px]" />
            <col />
            <col className="w-[132px]" />
            <col className="w-[100px]" />
            <col className="w-[84px]" />
            <col className="w-[150px]" />
          </colgroup>
          <thead>
            <tr className="border-b border-line bg-surface">
              {["ID", "Source", "Observation", "Timestamp", "Reliability", "Relevance", "Provenance"].map((heading) => (
                <th key={heading} scope="col" className="label px-3.5 py-2 font-normal first:pl-5">{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.ref} className="border-b border-line/60 transition-colors last:border-b-0 hover:bg-surface">
                <td className="py-2.5 pl-5 pr-3.5 align-top">
                  <button type="button" onClick={() => setSelected(item)} className="mono whitespace-nowrap text-xs underline decoration-line underline-offset-4 hover:decoration-fg">
                    {item.ref}
                  </button>
                </td>
                <td className="mono px-3.5 py-2.5 align-top text-xs text-dim">{item.source_key}</td>
                <td className="px-3.5 py-2.5 align-top text-dim">{item.observation}</td>
                <td className="mono px-3.5 py-2.5 align-top text-xs text-dim">{utc(item.observed_at)}</td>
                <td className="px-3.5 py-2.5 align-top"><Tag tone={RELIABILITY_TONE[item.reliability]}>{item.reliability}</Tag></td>
                <td className="px-3.5 py-2.5 align-top text-dim">{item.relevance}</td>
                <td className="mono truncate px-3.5 py-2.5 align-top text-xs text-dim" title={item.provenance.tool}>{item.provenance.tool}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && <EvidenceDrawer item={selected} investigationId={investigationId} onClose={() => setSelected(null)} />}
    </>
  );
}
