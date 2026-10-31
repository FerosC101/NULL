"use client";

import { ArrowLeft, Check, ChevronDown, CircleDashed, FileDown, Loader2, Minus, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useSession } from "@/components/shell";
import { AssessmentMark, Button, ErrorNote, Loading, SectionHeader, StatusText, Tag, useToast } from "@/components/ui";
import { EvidenceTable } from "@/components/workspace/evidence";
import { CompetingRealities } from "@/components/workspace/realities";
import { RecommendedInvestigation } from "@/components/workspace/recommended";
import { api, useApi } from "@/lib/api";
import { ago, duration, sentence, utc } from "@/lib/format";
import type { InvestigationDetail, ReportSummary, TimelineItem, ToolExecutionView } from "@/lib/types";

const RUNNING = new Set(["queued", "analyzing", "running_checks"]);

const LEDGER: { key: keyof InvestigationDetail["ledger"]; label: string; hint: string }[] = [
  { key: "observed", label: "Observed", hint: "Read directly from records" },
  { key: "inferred", label: "Inferred", hint: "Derived by the validators" },
  { key: "assumed", label: "Assumed", hint: "Taken as true, not tested" },
  { key: "unknown", label: "Unknown", hint: "Required and not yet seen" },
  { key: "would_change", label: "Could change this", hint: "Checks still open" },
];

const KINDS: Record<string, string> = {
  evidence_gap: "Evidence gap",
  unsupported_assumption: "Unsupported assumption",
  incomplete_observation: "Incomplete observation",
  measurement_bias: "Measurement bias",
};

const SEVERITY_DOT: Record<string, string> = { critical: "bg-bad", high: "bg-warn", medium: "bg-dim", low: "bg-mute" };

function StageIcon({ status }: { status: string }) {
  const common = "size-[18px] rounded-full border flex items-center justify-center shrink-0 bg-base";
  if (status === "done") return <span className={`${common} border-fg`}><Check size={10} strokeWidth={3} /></span>;
  if (status === "running") return <span className={`${common} border-fg`}><Loader2 size={10} className="animate-spin" /></span>;
  if (status === "failed") return <span className={`${common} border-bad text-bad`}><X size={10} strokeWidth={3} /></span>;
  if (status === "skipped") return <span className={`${common} border-line text-mute`}><Minus size={10} /></span>;
  return <span className={`${common} border-line`}><span className="sr-only">Pending</span></span>;
}

function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="relative">
      <span aria-hidden className="absolute bottom-3 left-[8.5px] top-3 w-px bg-line" />
      {items.map((item) => (
        <li key={item.stage} className="relative flex gap-3 pb-4 last:pb-0">
          <StageIcon status={item.status} />
          <div className="min-w-0">
            <p className={`text-[13px] leading-[18px] ${item.status === "pending" ? "text-mute" : ""}`}>{item.label}</p>
            {item.finished_at && <p className="mono text-[11px] text-mute">{utc(item.finished_at)}</p>}
            {item.status === "pending" && item.detail && <p className="text-xs text-dim">{item.detail}</p>}
            {item.status === "skipped" && <p className="text-xs text-mute">Skipped</p>}
            {item.status !== "pending" && item.detail && item.status !== "skipped" && (
              <p className="mt-0.5 text-xs text-dim">{item.detail}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function ToolHistory({ executions }: { executions: ToolExecutionView[] }) {
  const [open, setOpen] = useState(false);
  const failed = executions.filter((e) => e.status === "failed").length;
  const records = executions.reduce((total, e) => total + e.records_read, 0);
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center justify-between text-left">
        <span className="label">Tool execution history</span>
        <ChevronDown size={14} className={`text-dim transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      <p className="mt-1 text-xs text-dim">
        {executions.length} calls, {records.toLocaleString()} records read
        {failed > 0 && <span className="text-bad">, {failed} failed</span>}
      </p>
      {open && (
        <ul className="mt-3 space-y-2.5">
          {executions.map((execution) => (
            <li key={execution.id} className="text-xs">
              <span className="flex items-baseline justify-between gap-2">
                <span className={`mono truncate ${execution.status === "failed" ? "text-bad" : "text-dim"}`}>{execution.tool}</span>
                <span className="mono shrink-0 text-mute">{duration(execution.started_at, execution.finished_at)}</span>
              </span>
              <span className="text-mute">
                {execution.role}
                {execution.records_read > 0 && ` · ${execution.records_read.toLocaleString()} records`}
              </span>
              {execution.error && <span className="mt-0.5 block text-bad">{execution.error}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Ledger({ ledger }: { ledger: InvestigationDetail["ledger"] }) {
  const [active, setActive] = useState<keyof InvestigationDetail["ledger"]>(ledger.unknown?.length ? "unknown" : "inferred");
  const current = LEDGER.find((l) => l.key === active)!;
  const items = ledger[active] ?? [];
  return (
    <div className="rounded-lg border border-line">
      <div role="tablist" aria-label="Knowledge ledger" className="grid grid-cols-2 divide-line border-b border-line sm:grid-cols-5 sm:divide-x">
        {LEDGER.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={active === key}
            onClick={() => setActive(key)}
            className={`px-4 py-3 text-left transition-colors ${active === key ? "bg-raised" : "hover:bg-surface"}`}
          >
            <span className="mono block text-xl font-light">{ledger[key]?.length ?? 0}</span>
            <span className={`text-xs ${active === key ? "text-fg" : "text-dim"}`}>{label}</span>
          </button>
        ))}
      </div>
      <div role="tabpanel" className="px-5 py-4">
        <p className="label mb-2">{current.hint}</p>
        {items.length ? (
          <ul className="space-y-1.5 text-[13px] text-dim">
            {items.map((item) => <li key={item}>{item}</li>)}
          </ul>
        ) : (
          <p className="text-[13px] text-mute">Nothing in this category.</p>
        )}
      </div>
    </div>
  );
}

function Conclusion({ investigation }: { investigation: InvestigationDetail }) {
  const [truth, setTruth] = useState<{ narrative: string; matches: boolean; comparable: boolean; expected_assessment: string } | null>(null);
  const toast = useToast();
  const provisional = investigation.status !== "concluded";
  const supporting = [...new Set(investigation.realities.flatMap((r) => (r.claim_true ? r.supporting : r.contradicting)))];
  const against = [...new Set(investigation.realities.flatMap((r) => (r.claim_true ? r.contradicting : r.supporting)))];

  async function reveal() {
    try {
      setTruth(await api(`/investigations/${investigation.id}/ground-truth`));
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "Answer key unavailable", "bad");
    }
  }

  return (
    <div className="rounded-lg border border-line">
      <div className="p-6">
        <div className="flex flex-wrap items-center gap-3">
          <AssessmentMark value={investigation.assessment} large />
          {provisional && <Tag tone="warn">Provisional</Tag>}
        </div>
        <p className="mt-3 max-w-3xl text-[15px] text-dim">{investigation.assessment_rationale}</p>
      </div>
      <dl className="grid gap-6 border-t border-line p-6 md:grid-cols-3">
        <div>
          <dt className="label mb-2">Evidence for the claim</dt>
          <dd className="mono text-xs text-dim">{supporting.join("  ") || "None"}</dd>
          <dt className="label mb-2 mt-5">Evidence against the claim</dt>
          <dd className={`mono text-xs ${against.length ? "text-fg" : "text-dim"}`}>{against.join("  ") || "None"}</dd>
        </div>
        <div>
          <dt className="label mb-2">Assumptions</dt>
          {investigation.assumptions.map((assumption) => (
            <dd key={assumption.key} className="mb-1.5 flex gap-2 text-[13px] text-dim">
              <span className="mono mt-px shrink-0 text-[11px] text-mute">{assumption.status === "held" ? "HELD" : assumption.status === "violated" ? "FAIL" : "OPEN"}</span>
              {assumption.text}
            </dd>
          ))}
        </div>
        <div>
          <dt className="label mb-2">Limitations</dt>
          {investigation.limitations.map((limit) => (
            <dd key={limit} className="mb-1.5 text-[13px] text-dim">{limit}</dd>
          ))}
        </div>
      </dl>
      {investigation.status === "concluded" && (
        <div className="border-t border-line px-6 py-4">
          {truth ? (
            <div className="text-[13px]">
              <p className="label mb-1.5">Demo answer key</p>
              <p className="text-dim">{truth.narrative}</p>
              <p className="mt-2 flex items-center gap-2">
                {truth.comparable ? (
                  truth.matches ? (
                    <><Check size={13} className="text-ok" aria-hidden /> NULL&apos;s conclusion matches the answer key.</>
                  ) : (
                    <><X size={13} className="text-bad" aria-hidden /> The answer key expected {truth.expected_assessment} for the full claim.</>
                  )
                ) : (
                  <span className="text-dim">The answer key describes the full 24-hour access claim, so this investigation can&apos;t be scored against it.</span>
                )}
              </p>
            </div>
          ) : (
            <Button small onClick={reveal}>Reveal demo answer key</Button>
          )}
        </div>
      )}
    </div>
  );
}

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const [exporting, setExporting] = useState(false);
  const { data, error, reload } = useApi<InvestigationDetail>(`/investigations/${id}`, (d) => RUNNING.has(d.status));

  if (error && !data) {
    return (
      <main className="mx-auto max-w-3xl px-8 py-12">
        <ErrorNote message={error} onRetry={reload} />
      </main>
    );
  }
  if (!data) {
    return (
      <main className="mx-auto max-w-5xl px-8 py-12">
        <Loading rows={6} />
      </main>
    );
  }

  async function exportReport() {
    setExporting(true);
    try {
      const report = await api<ReportSummary>("/reports", { body: { investigation_id: id } });
      router.push(`/reports/${report.id}`);
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "The report couldn't be generated", "bad");
      setExporting(false);
    }
  }

  const running = RUNNING.has(data.status);

  async function refreshAfterDecision() {
    const updated = await reload();
    if (updated && RUNNING.has(updated.status)) {
      const poll = async () => {
        const next = await reload();
        if (next && RUNNING.has(next.status)) setTimeout(poll, 900);
      };
      poll();
    }
  }

  return (
    <main className="mx-auto max-w-[1280px] px-8 pb-24 pt-7 max-sm:px-4">
      <Link href="/investigations" className="mb-5 inline-flex items-center gap-1.5 text-[13px] text-dim transition-colors hover:text-fg">
        <ArrowLeft size={14} aria-hidden /> Investigations
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-5">
        <div>
          <h1 className="text-[26px] font-light leading-tight tracking-[-0.02em]">{data.name}</h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-dim">
            <span className="mono text-xs">{data.ref}</span>
            <StatusText status={data.status} />
            <span>Updated {ago(data.updated_at)}</span>
            <span>{data.assignee}</span>
            <span className="mono text-xs">{data.dataset_label} (synthetic)</span>
          </p>
        </div>
        {can("reports.write") && (
          <Button onClick={exportReport} busy={exporting} disabled={running}>
            <FileDown size={15} aria-hidden /> Export report
          </Button>
        )}
      </header>

      {data.error && <div className="mt-5"><ErrorNote message={`This investigation stopped: ${data.error}`} /></div>}

      <section aria-labelledby="claim-heading" className="grid gap-8 py-9 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div>
          <p id="claim-heading" className="label mb-3">Claim under review</p>
          <blockquote className="text-[30px] font-light leading-[1.22] tracking-[-0.022em]">{data.claim}</blockquote>
          {data.compiled_claim.interpretation && <p className="mt-4 max-w-2xl text-sm text-dim">{data.compiled_claim.interpretation}</p>}
        </div>
        <div className="lg:border-l lg:border-line lg:pl-8">
          <p className="label mb-3">Current assessment</p>
          {running ? (
            <p className="flex items-center gap-2 text-sm text-dim"><Loader2 size={14} className="animate-spin" aria-hidden /> Evaluating evidence</p>
          ) : (
            <>
              <AssessmentMark value={data.assessment} large />
              <p className="mt-3 text-sm text-dim">{data.assessment_rationale}</p>
            </>
          )}
        </div>
      </section>

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_268px]">
        <div className="min-w-0 space-y-12">
          <Ledger ledger={data.ledger} />

          {data.realities.length > 0 && (
            <section>
              <SectionHeader label="Counterfactual audit" title="Competing realities" description="Each reality predicts what the evidence should show. Only observations can separate them." />
              <CompetingRealities investigation={data} />
            </section>
          )}

          <section>
            <SectionHeader id="discovered" label="Analysis" title="What NULL discovered" />
            {data.findings.length ? (
              <ul className="divide-y divide-line border-y border-line">
                {data.findings.map((finding) => (
                  <li key={finding.id} className="grid gap-x-6 gap-y-1 py-4 md:grid-cols-[150px_minmax(0,1fr)]">
                    <p className="flex items-center gap-2 self-start text-xs text-dim">
                      <span aria-hidden className={`size-1.5 shrink-0 rounded-full ${SEVERITY_DOT[finding.severity]}`} />
                      {KINDS[finding.kind] ?? sentence(finding.kind)}
                    </p>
                    <div>
                      <h3 className="text-[15px]">
                        {finding.title}
                        <span className="sr-only"> Severity {finding.severity}.</span>
                      </h3>
                      <p className="mt-1 text-[13px] text-dim">{finding.body}</p>
                      {finding.evidence_refs.length > 0 && <p className="mono mt-1.5 text-[11px] text-mute">{finding.evidence_refs.join("  ")}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-dim">{running ? "Analysis in progress." : "No weaknesses were identified in the evidence examined."}</p>
            )}
          </section>

          <section>
            <SectionHeader id="recommended" label="Next step" title="Recommended investigation" />
            <RecommendedInvestigation investigation={data} onChanged={refreshAfterDecision} />
          </section>

          <section>
            <SectionHeader label="Traceability" title="Evidence analysis" description="Every item names the tool that produced it and the records it rests on. Select an ID to inspect it." />
            {data.evidence.length ? (
              <EvidenceTable evidence={data.evidence} investigationId={data.id} />
            ) : (
              <p className="text-sm text-dim">{running ? "Collecting evidence." : "No evidence was collected."}</p>
            )}
          </section>

          <section>
            <SectionHeader label="Conclusion" title="Investigation conclusion" />
            <Conclusion investigation={data} />
          </section>

          {data.remediations.length > 0 && (
            <section>
              <SectionHeader label="Mitigate" title="Corrective actions" action={<Link href="/assurance#mitigation" className="text-[13px] text-dim underline decoration-line underline-offset-4 hover:text-fg">Manage in Assurance</Link>} />
              <ul className="divide-y divide-line border-y border-line">
                {data.remediations.map((remediation) => (
                  <li key={remediation.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-[13px]">
                    <span className="min-w-0 flex-1"><span className="mono mr-3 text-xs text-mute">{remediation.ref}</span><span className="text-dim">{remediation.action}</span></span>
                    <Tag tone={remediation.verification_status === "verified" ? "ok" : "neutral"}>{remediation.verification_status.replace("_", " ")}</Tag>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside className="max-lg:order-first">
          <div className="space-y-8 lg:sticky lg:top-6">
            <section aria-label="Investigation timeline">
              <p className="label mb-4">Investigation timeline</p>
              <Timeline items={data.timeline} />
            </section>
            <section className="border-t border-line pt-5">
              <ToolHistory executions={data.tool_executions} />
            </section>
            <section className="border-t border-line pt-5">
              <p className="label mb-1.5">Reasoning</p>
              <p className="flex items-start gap-2 text-xs text-dim">
                <CircleDashed size={13} className="mt-0.5 shrink-0" aria-hidden />
                {data.reasoning_note || "Not started"}
              </p>
              {data.explorer_notes.length > 0 && (
                <details className="mt-2 text-xs text-dim">
                  <summary className="cursor-pointer transition-colors hover:text-fg">Explorer notes ({data.explorer_notes.length})</summary>
                  <ul className="mt-2 space-y-2">
                    {data.explorer_notes.map((note) => (
                      <li key={note.text}>
                        {note.text}
                        {note.evidence_refs.length > 0 && <span className="mono ml-1 text-[11px] text-mute">{note.evidence_refs.join(" ")}</span>}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </section>
          </div>
        </aside>
      </div>
    </main>
  );
}
