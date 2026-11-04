"use client";

import { ArrowLeft, Check, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Button, ErrorNote, Field, FormField, LinkButton, Loading, PageHeader, Tag, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { dataClass, utc } from "@/lib/format";
import type { ImportFileView, ImportOptions, ImportView } from "@/lib/types";

const SOURCES = [
  ["idp_auth", "Sign-in logs"],
  ["network", "Network flows"],
  ["edr", "Endpoint events"],
  ["coverage", "Endpoint agents"],
  ["inventory", "Asset register"],
  ["directory", "Windows logons, VPN sessions, change tickets or log forwarding"],
];

const ZONES = ["UTC", "Asia/Manila", "Asia/Singapore", "Asia/Tokyo", "Europe/London", "America/New_York", "America/Chicago", "America/Los_Angeles"];

function megabytes(size: number) {
  return size < 1e6 ? `${Math.max(1, Math.round(size / 1e3))} KB` : `${(size / 1e6).toFixed(1)} MB`;
}

function FileRow({ upload, file, options, onChanged }: { upload: ImportView; file: ImportFileView; options: ImportOptions; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const kind = options.kinds.find((k) => k.key === file.kind);
  const editable = upload.status === "draft";

  async function save(next: { kind?: string | null; mapping?: Record<string, string>; timezone?: string | null }) {
    setBusy(true);
    try {
      await api(`/imports/${upload.key}/files/${file.id}`, {
        method: "PUT",
        body: { kind: file.kind, mapping: file.mapping, timezone: file.timezone, ...next },
      });
      onChanged();
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "That change couldn't be saved", "bad");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api(`/imports/${upload.key}/files/${file.id}`, { method: "DELETE" });
      onChanged();
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "The file couldn't be removed", "bad");
      setBusy(false);
    }
  }

  return (
    <li className="py-3.5">
      <div className="grid items-center gap-x-5 gap-y-2 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1.1fr)_auto]">
        <p className="min-w-0">
          <span className="block truncate text-sm" title={file.name}>{file.name}</span>
          <span className="text-xs text-mute">{megabytes(file.size)}</span>
        </p>
        <select aria-label={`File type for ${file.name}`} className="field" disabled={!editable || busy} value={file.kind ?? ""} onChange={(event) => save({ kind: event.target.value || null, mapping: {} })}>
          <option value="">Choose a file type</option>
          {options.kinds.map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}
        </select>
        <p className={`text-[13px] ${file.ready && !file.rejected ? "text-dim" : "text-warn"}`}>
          {!file.kind
            ? "File type not recognized"
            : file.missing.length
              ? `Needs ${file.missing.join(", ")}`
              : `${file.accepted.toLocaleString()} of ${file.total_rows.toLocaleString()} rows readable`}
        </p>
        {editable && <Button small variant="ghost" aria-label={`Remove ${file.name}`} disabled={busy} onClick={remove}><Trash2 size={14} aria-hidden /></Button>}
      </div>
      {file.reasons.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[13px] text-warn">
          {file.reasons.slice(0, 5).map((reason) => <li key={reason.reason}>{reason.count.toLocaleString()} rejected: {reason.reason}</li>)}
        </ul>
      )}
      {file.notes.map((note) => <p key={note} className="mt-1 text-xs text-dim">{note}</p>)}
      {kind && (
        <details className="mt-1.5 text-xs text-dim" open={file.missing.length > 0}>
          <summary className="cursor-pointer transition-colors hover:text-fg">Columns and time zone</summary>
          <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {kind.columns.map((column) => (
              <FormField key={column.name} label={`${column.label}${column.required ? "" : " (optional)"}`}>
                <select className="field" disabled={!editable || busy} value={file.mapping[column.name] ?? ""} onChange={(event) => {
                  const mapping = { ...file.mapping };
                  if (event.target.value) mapping[column.name] = event.target.value;
                  else delete mapping[column.name];
                  save({ mapping });
                }}>
                  <option value="">Not in this file</option>
                  {file.columns.map((header) => <option key={header} value={header}>{header}</option>)}
                </select>
              </FormField>
            ))}
            <FormField label="Time zone of unmarked times">
              <select className="field" disabled={!editable || busy} value={file.timezone ?? ""} onChange={(event) => save({ timezone: event.target.value || null })}>
                <option value="">Times are marked, reject any that aren&apos;t</option>
                {ZONES.map((zone) => <option key={zone} value={zone}>{zone}</option>)}
              </select>
            </FormField>
          </div>
        </details>
      )}
    </li>
  );
}

export default function ImportPage() {
  const { key } = useParams<{ key: string }>();
  const router = useRouter();
  const toast = useToast();
  const { data: upload, error, reload } = useApi<ImportView>(`/imports/${key}`);
  const { data: options } = useApi<ImportOptions>("/imports/options");
  const picker = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [acceptRejected, setAcceptRejected] = useState(false);
  const [busy, setBusy] = useState(false);

  async function add(files: FileList | null) {
    if (!files?.length) return;
    const failed: string[] = [];
    let index = 0;
    for (const file of Array.from(files)) {
      index += 1;
      setProgress(`Reading ${file.name} (${index} of ${files.length})`);
      try {
        await api(`/imports/${key}/files?name=${encodeURIComponent(file.name)}`, { file });
      } catch (cause) {
        failed.push(`${file.name}: ${cause instanceof Error ? cause.message : "it couldn't be uploaded"}`);
      }
    }
    setProblems(failed);
    setProgress(null);
    if (picker.current) picker.current.value = "";
    reload();
  }

  async function commit() {
    setBusy(true);
    try {
      await api(`/imports/${key}/commit`, { body: { accept_rejected: acceptRejected } });
      toast("Added to evidence");
      reload();
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "The upload couldn't be committed", "bad");
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    setBusy(true);
    try {
      await api(`/imports/${key}`, { method: "DELETE" });
      router.push("/sources");
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "The upload couldn't be discarded", "bad");
      setBusy(false);
    }
  }

  async function investigate() {
    setBusy(true);
    try {
      await api("/sources/snapshot", { body: { dataset: key } });
      window.location.assign("/investigations/new");
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "The dataset couldn't be selected", "bad");
      setBusy(false);
    }
  }

  const back = (
    <Link href="/sources" className="mb-8 inline-flex items-center gap-1.5 text-[13px] text-dim transition-colors hover:text-fg">
      <ArrowLeft size={14} aria-hidden /> Sources
    </Link>
  );
  if (error && !upload) return <main className="mx-auto max-w-[1180px] px-8 py-10 max-sm:px-4">{back}<ErrorNote message={error} onRetry={reload} /></main>;
  if (!upload || !options) return <main className="mx-auto max-w-[1180px] px-8 py-10 max-sm:px-4">{back}<Loading /></main>;

  const covered = new Set(upload.files.filter((f) => f.ready).map((f) => f.source));
  const rejected = upload.files.reduce((sum, f) => sum + f.rejected, 0);
  const allReady = upload.files.length > 0 && upload.files.every((f) => f.ready);
  const draft = upload.status === "draft";

  return (
    <main className="mx-auto max-w-[1180px] px-8 py-10 max-sm:px-4">
      {back}
      <PageHeader title={upload.label} description={draft ? "Add your exports, check how each was read, then add them to evidence." : "Added to evidence. These records can't be changed."} action={<Tag>{dataClass(upload.data_class)}</Tag>} />
      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0 space-y-6">
          {draft && (
            <div className="rounded-lg border border-dashed border-line px-5 py-7 text-center">
              <input ref={picker} type="file" accept=".csv,.tsv,text/csv" multiple className="sr-only" tabIndex={-1} aria-label="CSV files to upload" onChange={(event) => add(event.target.files)} />
              <Button busy={progress !== null} onClick={() => picker.current?.click()}><Upload size={15} aria-hidden /> Choose CSV files</Button>
              <p className="mt-2 text-[13px] text-dim" aria-live="polite">{progress ?? `Up to ${Math.round(options.max_bytes / 1048576)} MB each. UTF-8 or UTF-16, with a header row and ISO 8601 times.`}</p>
            </div>
          )}
          {problems.length > 0 && <ul className="space-y-1 text-[13px] text-bad">{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>}
          {upload.files.length > 0 && <ul className="divide-y divide-line border-y border-line">{upload.files.map((file) => <FileRow key={file.id} upload={upload} file={file} options={options} onChanged={reload} />)}</ul>}
          {draft && rejected > 0 && (
            <label className="flex items-start gap-2.5 text-[13px]">
              <input type="checkbox" className="mt-0.5 accent-white" checked={acceptRejected} onChange={(event) => setAcceptRejected(event.target.checked)} />
              Continue without the {rejected.toLocaleString()} rejected rows. Anything they recorded will be missing from the evidence, and your conclusions may be weaker.
            </label>
          )}
          {draft ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" busy={busy} disabled={!allReady || (rejected > 0 && !acceptRejected)} onClick={commit}>Add to evidence</Button>
              <Button variant="ghost" disabled={busy} onClick={discard}>Discard upload</Button>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" busy={busy} onClick={investigate}>Start an investigation</Button>
              <LinkButton href="/sources">Back to Sources</LinkButton>
            </div>
          )}
        </div>
        <aside className="space-y-6">
          {!draft && (
            <dl className="space-y-4">
              <Field label="Records">{(upload.summary.total ?? 0).toLocaleString()}</Field>
              <Field label="Period covered"><span className="mono text-xs">{utc(upload.window_start)} to {utc(upload.window_end)}</span></Field>
              {(upload.summary.sessions_inferred ?? 0) > 0 && <Field label="Sessions matched by time">{upload.summary.sessions_inferred?.toLocaleString()}</Field>}
            </dl>
          )}
          <section aria-labelledby="sources-needed">
            <h2 id="sources-needed" className="label mb-2">Sources in this upload</h2>
            <ul className="space-y-1.5 text-[13px]">
              {SOURCES.map(([source, label]) => {
                const present = draft ? covered.has(source) : !upload.summary.missing_sources?.includes(source);
                return (
                  <li key={source} className={`flex gap-2 ${present ? "" : "text-dim"}`}>
                    <span className="mt-0.5 w-3.5 shrink-0">{present && <Check size={13} className="text-ok" aria-label="Present" />}</span>
                    {label}
                  </li>
                );
              })}
            </ul>
            <p className="mt-2 text-xs text-mute">NULL reports what a missing source stops it from testing. It never treats missing records as a clean result.</p>
          </section>
        </aside>
      </div>
    </main>
  );
}
