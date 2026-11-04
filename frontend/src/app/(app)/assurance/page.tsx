"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { RemediationRow, VerificationList } from "@/components/assurance/actions";
import { ActionPipeline, HostTicks, type PipelineStage } from "@/components/charts";
import { Empty, ErrorNote, Loading, PageHeader, SectionHeader, Tag } from "@/components/ui";
import { useApi } from "@/lib/api";
import { utc } from "@/lib/format";
import type { AssuranceData, RemediationView } from "@/lib/types";

const CLASS_LABEL: Record<string, string> = { workstation: "Workstations", server: "Servers", ot_gateway: "OT gateways" };

/** Exactly one stage per action. Executed but unverified is never counted as done. */
function stageOf(r: RemediationView) {
  if (r.approval_status === "rejected") return "rejected";
  if (r.verification_status === "verified") return "verified";
  if (r.verification_status === "failed" || r.verification_status === "recurred") return "failed";
  if (r.execution_status === "executed") return "pending";
  if (r.approval_status === "approved") return "approved";
  return "awaiting";
}

const STAGES: { key: string; label: string; mark: string }[] = [
  { key: "awaiting", label: "Awaiting approval", mark: "bg-mute" },
  { key: "approved", label: "Approved, not executed", mark: "bg-dim" },
  { key: "pending", label: "Pending verification", mark: "bg-warn" },
  { key: "failed", label: "Failed or recurred", mark: "bg-bad" },
  { key: "verified", label: "Verified", mark: "bg-ok" },
  { key: "rejected", label: "Rejected", mark: "bg-raised" },
];

export default function AssurancePage() {
  const { data, error, reload } = useApi<AssuranceData>("/assurance");
  const [filter, setFilter] = useState<string | null>(null);
  const pipeline: PipelineStage[] = useMemo(
    () => STAGES.map((stage) => ({ ...stage, items: (data?.remediations ?? []).filter((r) => stageOf(r) === stage.key).map((r) => ({ ref: r.ref, title: r.action })) })),
    [data],
  );
  if (error && !data) return <main className="mx-auto max-w-3xl px-8 py-12"><ErrorNote message={error} onRetry={reload} /></main>;
  if (!data) return <main className="mx-auto max-w-[1100px] px-8 py-12"><Loading rows={6} /></main>;

  const { preventive, remediations } = data;
  const coverage = preventive.coverage;
  const unresolved = remediations.filter((r) => r.verification_status !== "verified" && r.approval_status !== "rejected");
  const openFindings = new Set(unresolved.map((r) => r.finding));
  const recurring = remediations.filter((r) => r.verification_status === "recurred");
  const shown = (filter ? remediations.filter((r) => stageOf(r) === filter) : remediations.filter((r) => r.verification_status !== "verified")).filter((r) => filter === "rejected" || r.approval_status !== "rejected");
  const executed = remediations.filter((r) => r.execution_status === "executed");
  const assumptions = preventive.unverified_assumptions;
  const filterName = STAGES.find((s) => s.key === filter)?.label;

  return (
    <main className="mx-auto max-w-[1100px] px-8 pb-24 pt-10 max-sm:px-4">
      <PageHeader
        title="Assurance"
        description={`${openFindings.size} open ${openFindings.size === 1 ? "finding" : "findings"} across ${unresolved.length} unresolved ${unresolved.length === 1 ? "action" : "actions"}${recurring.length ? `, ${recurring.length} recurring` : ""}.`}
      />

      <section aria-label="Where corrective actions stand" className="mb-12 border-y border-line">
        <ActionPipeline stages={pipeline} active={filter} onSelect={setFilter} />
      </section>

      <section className="mb-14">
        <SectionHeader id="mitigation" title="Corrective actions" description={filterName ? `Showing: ${filterName}.` : "Every action needs an approval, an execution, and evidence that it worked."} />
        {shown.length ? (
          <ul className="divide-y divide-line border-y border-line">
            {shown.map((remediation) => <RemediationRow key={remediation.id} remediation={remediation} onChanged={reload} />)}
          </ul>
        ) : (
          <Empty title={filter ? "Nothing in this stage" : "No open actions"}>{filter ? "Select another stage to see its actions." : "Corrective actions appear here when an investigation finds a weakness."}</Empty>
        )}
      </section>

      <section className="mb-14">
        <SectionHeader id="verification" title="Continuous verification" description="A remediation is resolved only when its verification procedure passes. Clicking a button can't resolve it." />
        <VerificationList rows={executed} onChanged={reload} />
      </section>

      <section>
        <SectionHeader id="preventive" title="Evidence environment" description={`Measured from current records in Snapshot ${preventive.dataset}.`} />
        {preventive.unavailable.map((item) => <div key={item.key} className="mb-3"><ErrorNote message={`${item.key}: ${item.reason}. Part of this section can't be measured.`} /></div>)}
        {coverage && (
          <>
            <ul className="space-y-3">
              {coverage.by_class.map((row) => (
                <li key={row.asset_class} className="grid items-center gap-x-5 gap-y-1 md:grid-cols-[130px_minmax(0,1fr)_72px]">
                  <span className="text-[13px]">{CLASS_LABEL[row.asset_class] ?? row.asset_class}</span>
                  <div>
                    <HostTicks total={row.hosts} flagged={row.uncovered} label={CLASS_LABEL[row.asset_class] ?? row.asset_class} />
                    {row.uncovered.length > 0 && <p className="mono mt-1 text-[11px] text-dim">{row.uncovered.join("  ")}</p>}
                  </div>
                  <span className="mono text-xs text-dim md:text-right">{row.reporting} / {row.hosts}</span>
                </li>
              ))}
            </ul>
            {(coverage.never_enrolled.length > 0 || coverage.stale.length > 0) && (
              <p className="mt-3 text-xs text-dim">
                {coverage.reporting} of {coverage.hosts} hosts reporting. {coverage.never_enrolled.length} never enrolled. {coverage.stale.length} enrolled but silent, which an enrollment count would show as covered.
              </p>
            )}
          </>
        )}
        <div className="mt-8 grid gap-x-10 gap-y-7 md:grid-cols-3">
          <div>
            <h3 className="mb-2 text-[15px]">Disconnected sources</h3>
            {preventive.disconnected_sources.length ? (
              <ul className="space-y-1.5 text-[13px]">
                {preventive.disconnected_sources.map((source) => (
                  <li key={source.key} className="flex items-center justify-between gap-3"><span>{source.name}</span><Tag tone="bad">Disconnected</Tag></li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-dim">Every source is connected.</p>}
          </div>
          <div>
            <h3 className="mb-2 text-[15px]">Collection weaknesses</h3>
            {preventive.collection_weaknesses.length ? (
              <ul className="space-y-1.5 text-[13px]">
                {preventive.collection_weaknesses.map((gap) => (
                  <li key={gap.subnet}>{gap.subnet}<span className="mono block text-[11px] text-dim">{gap.missing_hours}h missing from {utc(gap.first)}</span></li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-dim">No gaps in the current window.</p>}
          </div>
          <div>
            <h3 className="mb-2 text-[15px]">Emerging risks</h3>
            {preventive.emerging_risks.length ? (
              <ul className="space-y-1.5 text-[13px]">
                {preventive.emerging_risks.map((risk) => <li key={risk.title}>{risk.title}<span className="block text-xs text-dim">{risk.body}</span></li>)}
              </ul>
            ) : <p className="text-[13px] text-dim">None detected.</p>}
          </div>
        </div>
        {assumptions.length > 0 && (
          <details className="mt-7 text-[13px]">
            <summary className="cursor-pointer text-dim transition-colors hover:text-fg">{assumptions.length} unverified or violated assumptions</summary>
            <ul className="mt-2 divide-y divide-line/60 border-y border-line">
              {assumptions.map((assumption) => (
                <li key={`${assumption.investigation_id}-${assumption.text}`} className="flex items-start justify-between gap-3 py-2">
                  <span className="text-dim">{assumption.text}</span>
                  <Link href={`/investigations/${assumption.investigation_id}`} className="mono shrink-0 text-[11px] text-dim underline decoration-line underline-offset-4 hover:text-fg">{assumption.investigation_ref}</Link>
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </main>
  );
}
