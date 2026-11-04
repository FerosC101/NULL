"use client";

import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { MiniRail } from "@/components/lifecycle";
import { useSession } from "@/components/shell";
import { AssessmentMark, Empty, ErrorNote, Loading, LinkButton, PageHeader, StatusText } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago } from "@/lib/format";
import type { InvestigationCard } from "@/lib/types";

const STATUSES = [
  ["", "All statuses"],
  ["awaiting_approval", "Awaiting approval"],
  ["analyzing", "Analyzing"],
  ["running_checks", "Running checks"],
  ["concluded", "Concluded"],
  ["failed", "Failed"],
];

const ASSESSMENTS = ["SUPPORTED", "CONTRADICTED", "PARTIALLY IDENTIFIED", "UNDERDETERMINED", "UNVERIFIED"];

export default function InvestigationsPage() {
  const { can } = useSession();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [assessment, setAssessment] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    if (assessment) params.set("assessment", assessment);
    if (since) params.set("since", new Date(`${since}T00:00:00Z`).toISOString());
    if (until) params.set("until", new Date(`${until}T23:59:59Z`).toISOString());
    return params.toString();
  }, [q, status, assessment, since, until]);
  const { data, error, loading, reload } = useApi<InvestigationCard[]>(`/investigations${query ? `?${query}` : ""}`);
  const filtered = Boolean(query);

  return (
    <main className="mx-auto max-w-[1180px] px-8 py-10 max-sm:px-4">
      <PageHeader
        title="Investigations"
        description="Claims under examination, and what the evidence could establish about each."
        action={can("investigations.write") && (
          <LinkButton href="/investigations/new" variant="primary"><Plus size={15} aria-hidden /> New investigation</LinkButton>
        )}
      />
      <div className="mb-5 flex flex-wrap items-center gap-2.5">
        <div className="relative min-w-60 flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-mute" aria-hidden />
          <input aria-label="Search investigations" className="field !pl-8" placeholder="Search name, claim or ID" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select aria-label="Status" className="field !w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select aria-label="Conclusion" className="field !w-auto" value={assessment} onChange={(e) => setAssessment(e.target.value)}>
          <option value="">All conclusions</option>
          {ASSESSMENTS.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <details className="text-[13px] text-dim">
          <summary className="cursor-pointer transition-colors hover:text-fg">Dates</summary>
          <span className="mt-2 flex flex-wrap gap-2">
            <input aria-label="Created from" type="date" className="field !w-auto" value={since} onChange={(e) => setSince(e.target.value)} />
            <input aria-label="Created until" type="date" className="field !w-auto" value={until} onChange={(e) => setUntil(e.target.value)} />
          </span>
        </details>
      </div>

      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && data.length === 0 && (
        filtered ? (
          <Empty title="No investigations match these filters">Change or clear the filters to see more.</Empty>
        ) : (
          <Empty title="No investigations yet" action={can("investigations.write") && <LinkButton href="/investigations/new" variant="primary">Start Investigation</LinkButton>}>
            Begin with a claim someone would like to rely on.
          </Empty>
        )
      )}
      {data && data.length > 0 && (
        <ul className="divide-y divide-line border-y border-line">
          {data.map((investigation) => (
            <li key={investigation.id}>
              <Link href={`/investigations/${investigation.id}`} className="-mx-3 grid gap-x-8 gap-y-2 rounded-md px-3 py-4 transition-colors hover:bg-surface md:grid-cols-[minmax(0,1fr)_260px]">
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="text-[15px]">{investigation.name}</span>
                    <span className="mono text-[11px] text-mute">{investigation.ref}</span>
                    <AssessmentMark value={investigation.assessment} />
                  </span>
                  <span className="mt-0.5 block truncate text-[13px] text-dim">{investigation.claim}</span>
                  {investigation.key_finding && <span className="mt-0.5 block truncate text-xs text-mute">{investigation.key_finding.title}</span>}
                </span>
                <span className="min-w-0">
                  <MiniRail stages={investigation.stages} />
                  <span className="mt-2 block truncate text-[13px]">{investigation.next_action.label}</span>
                  <span className="flex flex-wrap items-center gap-x-2 text-xs text-mute"><StatusText status={investigation.status} /> · {ago(investigation.updated_at)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
