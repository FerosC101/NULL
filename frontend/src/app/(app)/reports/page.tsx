"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useSession } from "@/components/shell";
import { AssessmentMark, Button, Empty, ErrorNote, Loading, PageHeader, Tag, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { utc } from "@/lib/format";
import type { InvestigationSummary, ReportSummary } from "@/lib/types";

export default function ReportsPage() {
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const { data, error, reload } = useApi<ReportSummary[]>("/reports");
  const { data: investigations } = useApi<InvestigationSummary[]>("/investigations");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const usable = investigations?.filter((i) => !["queued", "analyzing", "running_checks"].includes(i.status)) ?? [];
  const chosen = target || usable[0]?.id || "";
  const grouped = useMemo(() => {
    const byInvestigation = new Map<string, ReportSummary[]>();
    for (const report of data ?? []) byInvestigation.set(report.investigation_id, [...(byInvestigation.get(report.investigation_id) ?? []), report]);
    return [...byInvestigation.values()].map((rows) => [...rows].sort((a, b) => b.version - a.version));
  }, [data]);

  async function generate() {
    setBusy(true);
    try {
      const report = await api<ReportSummary>("/reports", { body: { investigation_id: chosen } });
      router.push(`/reports/${report.id}`);
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "The report couldn't be generated", "bad");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-[1000px] px-8 py-10 max-sm:px-4">
      <PageHeader
        title="Reports"
        description="Frozen, hashed records of what an investigation established at a point in time."
        action={can("reports.write") && usable.length > 0 && (
          <div className="flex max-w-full flex-wrap items-center gap-2">
            <select aria-label="Investigation to report on" className="field !w-auto max-w-64 min-w-0" value={chosen} onChange={(event) => setTarget(event.target.value)}>
              {usable.map((i) => <option key={i.id} value={i.id}>{i.ref} {i.name}</option>)}
            </select>
            <Button variant="primary" busy={busy} disabled={!chosen} onClick={generate}>Generate report</Button>
          </div>
        )}
      />
      {error && <ErrorNote message={error} onRetry={reload} />}
      {!data && !error && <Loading rows={3} />}
      {data?.length === 0 && <Empty title="No reports yet">Generate one from an investigation. It records the evidence as it stands, including what remains unknown.</Empty>}
      {data && data.length > 0 && (
        <ul className="divide-y divide-line border-y border-line">
          {grouped.map((versions) => {
            const [latest, ...earlier] = versions;
            return (
              <li key={latest.investigation_id} className="py-3.5">
                <Link href={`/reports/${latest.id}`} className="-mx-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-1 rounded-md px-3 py-1 transition-colors hover:bg-surface">
                  <span className="min-w-0 flex-1 basis-80">
                    <span className="text-[15px]">{latest.name}</span>
                    <span className="mono mt-0.5 block text-[11px] text-mute">{latest.ref} · version {latest.version} · {latest.investigation_ref} · {utc(latest.created_at)} · {latest.sha256.slice(0, 12)}</span>
                  </span>
                  <span className="flex items-center gap-3">
                    {latest.provisional && <Tag tone="warn">Provisional</Tag>}
                    <AssessmentMark value={latest.assessment} />
                  </span>
                </Link>
                {earlier.length > 0 && (
                  <details className="mt-1 text-xs text-dim">
                    <summary className="cursor-pointer transition-colors hover:text-fg">{earlier.length} earlier {earlier.length === 1 ? "version" : "versions"}</summary>
                    <ul className="mt-1.5 space-y-1">
                      {earlier.map((report) => (
                        <li key={report.id}>
                          <Link href={`/reports/${report.id}`} className="mono text-[11px] underline decoration-line underline-offset-4 hover:text-fg">{report.ref} · version {report.version} · {utc(report.created_at)} · {report.assessment}</Link>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
