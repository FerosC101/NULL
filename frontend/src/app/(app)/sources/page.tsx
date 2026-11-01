"use client";

import { Lock } from "lucide-react";
import { useState } from "react";
import { ChartFrame, CoverageMatrix, matrixTable } from "@/components/charts";
import { useSession } from "@/components/shell";
import { Button, ErrorNote, Field, Loading, Modal, PageHeader, Tag, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, utc } from "@/lib/format";
import type { CoverageMatrixData, SourceView } from "@/lib/types";

interface SourcesData {
  active_dataset: string;
  datasets: { key: string; label: string }[];
  sources: SourceView[];
}

function SourceRow({ source, onChanged }: { source: SourceView; onChanged: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const connected = source.status === "connected";
  const manage = can("sources.manage");

  async function act(path: string, success: string) {
    setBusy(true);
    try {
      await api(`/sources/${source.key}/${path}`, { method: "POST" });
      toast(success);
      onChanged();
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "That action failed", "bad");
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <li className="py-3.5">
      <div className="grid items-baseline gap-x-6 gap-y-1 md:grid-cols-[minmax(0,1.3fr)_110px_150px_minmax(0,1fr)_auto]">
        <h3 className="flex min-w-0 items-center gap-2 text-[15px]">
          {source.name}
          {source.restricted && <Lock size={12} className="shrink-0 text-dim" aria-label="Restricted source" />}
        </h3>
        <p className={`flex items-center gap-2 text-[13px] ${connected ? "text-dim" : "text-bad"}`}>
          <span aria-hidden className={`size-1.5 rounded-full ${connected ? "bg-ok" : "bg-bad"}`} />
          {connected ? "Connected" : "Disconnected"}
        </p>
        <p className="mono text-xs text-dim">{source.latest ? utc(source.latest) : "No data"}</p>
        <p className="text-[13px] text-dim">{source.coverage ?? (source.records ? `${source.records.toLocaleString()} records` : "No records")}</p>
        {manage && (
          <div className="flex gap-1.5">
            {connected ? (
              <>
                <Button small busy={busy} onClick={() => act("sync", `${source.name} re-read: ${source.records.toLocaleString()} records`)}>Re-read</Button>
                <Button small variant="ghost" onClick={() => setConfirming(true)}>Disconnect</Button>
              </>
            ) : (
              <Button small busy={busy} onClick={() => act("connect", `${source.name} connected`)}>Connect</Button>
            )}
          </div>
        )}
      </div>
      <details className="mt-1 text-xs text-dim">
        <summary className="cursor-pointer transition-colors hover:text-fg">Details</summary>
        <p className="mt-1.5 text-[13px]">{source.description}</p>
        <dl className="mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-4">
          <Field label="Mode"><Tag>{source.mode}</Tag></Field>
          <Field label="Available records"><span className="mono text-[13px]">{source.records.toLocaleString()}</span></Field>
          <Field label="Last synchronization"><span className="text-[13px]">{connected ? ago(source.last_sync_at) : "Not connected"}</span></Field>
          <Field label="Permissions"><span className="flex flex-wrap gap-1.5">{source.permissions.map((p) => <Tag key={p}>{p}</Tag>)}</span></Field>
        </dl>
      </details>
      {confirming && (
        <Modal open label={source.name} title="Disconnect this source?" onClose={() => setConfirming(false)} footer={<><Button onClick={() => setConfirming(false)}>Cancel</Button><Button variant="danger" busy={busy} onClick={() => act("disconnect", `${source.name} disconnected`)}>Disconnect</Button></>}>
          <p className="text-sm text-dim">Investigations won&apos;t be able to read this source. Checks that need it will be blocked, and NULL will report them as blocked.</p>
        </Modal>
      )}
    </li>
  );
}

export default function SourcesPage() {
  const { can } = useSession();
  const toast = useToast();
  const { data, error, reload } = useApi<SourcesData>("/sources");
  const { data: coverage, reload: reloadCoverage } = useApi<CoverageMatrixData>("/sources/coverage");
  const refresh = () => {
    reload();
    reloadCoverage();
  };

  async function changeSnapshot(dataset: string) {
    try {
      await api("/sources/snapshot", { body: { dataset } });
      refresh();
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "The snapshot couldn't be changed", "bad");
    }
  }

  return (
    <main className="mx-auto max-w-[1180px] px-8 py-10 max-sm:px-4">
      <PageHeader
        title="Sources"
        description="NULL can only know what these sources can show."
        action={data && (
          <label className="flex items-center gap-2 text-[13px] text-dim">
            Demo snapshot
            <select className="field !w-auto" disabled={!can("sources.manage")} value={data.active_dataset} onChange={(event) => changeSnapshot(event.target.value)}>
              {data.datasets.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
            </select>
          </label>
        )}
      />
      {error && !data && <ErrorNote message={error} onRetry={reload} />}
      {!data && !error && <Loading rows={4} />}
      {data && (
        <div className="space-y-11">
          <p className="border-y border-dashed border-line py-3 text-[13px] text-dim">
            No live integrations are connected. Everything here is simulated data for a fictional company, loaded from a fixed snapshot. Adding a live connector isn&apos;t available yet.
          </p>
          {coverage && (
            <ChartFrame
              title="Collection health"
              interpretation={coverage.interpretation}
              period={`${utc(coverage.window.start)} to ${utc(coverage.window.end)}`}
              table={matrixTable(coverage)}
            >
              <CoverageMatrix matrix={coverage} />
            </ChartFrame>
          )}
          <section aria-labelledby="sources-heading">
            <h2 id="sources-heading" className="mb-2 text-[15px]">Simulated sources</h2>
            <ul className="divide-y divide-line border-y border-line">
              {data.sources.map((source) => <SourceRow key={source.key} source={source} onChanged={refresh} />)}
            </ul>
          </section>
        </div>
      )}
    </main>
  );
}
