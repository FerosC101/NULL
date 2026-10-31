"use client";

import { Lock } from "lucide-react";
import { useState } from "react";
import { useSession } from "@/components/shell";
import { Button, ErrorNote, Field, Loading, Modal, PageHeader, Tag, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, utc } from "@/lib/format";
import type { SourceView } from "@/lib/types";

interface SourcesData {
  active_dataset: string;
  datasets: { key: string; label: string }[];
  sources: SourceView[];
}

function SourceCard({ source, onChanged }: { source: SourceView; onChanged: () => void }) {
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
    <article className="flex flex-col rounded-lg border border-line p-5">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-[15px]">
            {source.name}
            {source.restricted && <Lock size={12} className="text-dim" aria-label="Restricted source" />}
          </h2>
          <p className="mt-0.5 text-[13px] text-dim">{source.description}</p>
        </div>
        <Tag>{source.mode}</Tag>
      </header>
      <p className={`mt-4 flex items-center gap-2 text-[13px] ${connected ? "" : "text-bad"}`}>
        <span aria-hidden className={`size-1.5 rounded-full ${connected ? "bg-ok" : "bg-bad"}`} />
        {connected ? "Connected" : "Disconnected"}
      </p>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-line pt-4">
        <Field label="Available records"><span className="mono text-[13px] text-fg">{source.records.toLocaleString()}</span></Field>
        <Field label="Last synchronization"><span className="text-[13px]">{connected ? ago(source.last_sync_at) : "Not connected"}</span></Field>
        <Field label="Data freshness"><span className="mono text-xs">{source.latest ? utc(source.latest) : "No data"}</span></Field>
        <Field label="Coverage"><span className="text-[13px]">{source.coverage ?? (source.records ? "Not measured" : "None")}</span></Field>
      </dl>
      <div className="mt-3">
        <Field label="Permissions">
          <span className="flex flex-wrap gap-1.5">{source.permissions.map((p) => <Tag key={p}>{p}</Tag>)}</span>
        </Field>
      </div>
      {manage && (
        <div className="mt-4 flex gap-2 border-t border-line pt-3.5">
          {connected ? (
            <>
              <Button small busy={busy} onClick={() => act("sync", `${source.name} re-read: ${source.records.toLocaleString()} records`)}>Re-read records</Button>
              <Button small variant="ghost" onClick={() => setConfirming(true)}>Disconnect</Button>
            </>
          ) : (
            <Button small busy={busy} onClick={() => act("connect", `${source.name} connected`)}>Connect</Button>
          )}
        </div>
      )}
      {confirming && (
        <Modal open label={source.name} title="Disconnect this source?" onClose={() => setConfirming(false)} footer={<><Button onClick={() => setConfirming(false)}>Cancel</Button><Button variant="danger" busy={busy} onClick={() => act("disconnect", `${source.name} disconnected`)}>Disconnect</Button></>}>
          <p className="text-sm text-dim">Investigations won&apos;t be able to read this source. Checks that need it will be blocked, and NULL will report them as blocked.</p>
        </Modal>
      )}
    </article>
  );
}

export default function SourcesPage() {
  const { can } = useSession();
  const toast = useToast();
  const { data, error, reload } = useApi<SourcesData>("/sources");

  async function changeSnapshot(dataset: string) {
    try {
      await api("/sources/snapshot", { body: { dataset } });
      reload();
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "The snapshot couldn't be changed", "bad");
    }
  }

  return (
    <main className="mx-auto max-w-[1180px] px-8 py-10 max-sm:px-4">
      <PageHeader
        title="Data Sources"
        description="The evidence environment. NULL can only know what these sources can show."
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
        <>
          <section aria-labelledby="live-heading" className="mb-8 rounded-lg border border-dashed border-line px-5 py-4">
            <h2 id="live-heading" className="text-[15px]">Live integrations</h2>
            <p className="mt-0.5 text-[13px] text-dim">
              No live integrations are connected. Everything below is simulated data for a fictional company, loaded from a fixed snapshot. Adding a live connector isn&apos;t available yet.
            </p>
          </section>
          <h2 className="label mb-3">Simulated sources</h2>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.sources.map((source) => <SourceCard key={source.key} source={source} onChanged={reload} />)}
          </div>
        </>
      )}
    </main>
  );
}
