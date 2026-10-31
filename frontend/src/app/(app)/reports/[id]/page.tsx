"use client";

import { ArrowLeft, FileDown, Printer, Table2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";
import { AssessmentMark, Button, ErrorNote, Field, Loading, Tag } from "@/components/ui";
import { useApi } from "@/lib/api";
import { utc } from "@/lib/format";
import type { Assessment, ReportSummary } from "@/lib/types";

/* eslint-disable @typescript-eslint/no-explicit-any */
interface FullReport extends ReportSummary {
  snapshot: any;
  sections: string[];
}

function Section({ index, title, kind, children }: { index: number; title: string; kind?: "Observed" | "Hypothesis" | "Analytical conclusion"; children: ReactNode }) {
  return (
    <section className="border-t border-line py-7 first:border-t-0">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-[19px] font-normal tracking-[-0.01em]">
          <span className="mono mr-3 text-xs text-mute">{String(index).padStart(2, "0")}</span>
          {title}
        </h2>
        {kind && <Tag tone={kind === "Hypothesis" ? "warn" : "neutral"}>{kind}</Tag>}
      </div>
      {children}
    </section>
  );
}

function Rows({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[13px]">
        <thead>
          <tr className="border-b border-line">
            {head.map((heading) => <th key={heading} scope="col" className="label py-1.5 pr-4 font-normal">{heading}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-b border-line/50 last:border-b-0">
              {row.map((cell, cellIndex) => <td key={cellIndex} className="py-2 pr-4 align-top text-dim">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, reload } = useApi<FullReport>(`/reports/${id}`);
  if (error && !data) return <main className="mx-auto max-w-3xl px-8 py-12"><ErrorNote message={error} onRetry={reload} /></main>;
  if (!data) return <main className="mx-auto max-w-3xl px-8 py-12"><Loading rows={6} /></main>;
  const s = data.snapshot;
  const t = data.sections;
  const executed = s.procedures.filter((p: any) => ["completed", "blocked", "failed"].includes(p.status));

  return (
    <main className="print-sheet mx-auto max-w-[860px] px-8 pb-24 pt-8 max-sm:px-4">
      <div className="no-print mb-7 flex flex-wrap items-center justify-between gap-3">
        <Link href="/reports" className="inline-flex items-center gap-1.5 text-[13px] text-dim transition-colors hover:text-fg">
          <ArrowLeft size={14} aria-hidden /> Reports
        </Link>
        <div className="flex gap-2">
          <Button small onClick={() => window.print()}><Printer size={13} aria-hidden /> Print</Button>
          <a href={`/api/v1/reports/${id}/evidence.csv`} className="inline-flex h-7 items-center gap-2 rounded-md border border-line px-2.5 text-[13px] font-medium transition-colors hover:bg-raised"><Table2 size={13} aria-hidden /> CSV</a>
          <a href={`/api/v1/reports/${id}/export.pdf`} className="inline-flex h-7 items-center gap-2 rounded-md border border-fg bg-fg px-2.5 text-[13px] font-medium text-void transition-colors hover:bg-dim"><FileDown size={13} aria-hidden /> PDF</a>
        </div>
      </div>
      <header className="mb-4">
        <p className="label mb-2">Investigation report · {data.ref}</p>
        <h1 className="text-[34px] font-light leading-[1.15] tracking-[-0.025em]">{s.investigation.name}</h1>
        <p className="mt-2 text-[13px] text-dim">
          {s.investigation.ref} · Generated {utc(data.created_at)} · {s.investigation.assignee}
        </p>
        <p className="mt-1 text-[13px] text-dim">{s.demo_notice}</p>
      </header>

      <Section index={1} title={t[0]} kind="Analytical conclusion">
        <AssessmentMark value={s.executive_summary.assessment as Assessment} large />
        <p className="mt-2.5 text-[15px] text-dim">{s.executive_summary.rationale}</p>
        <p className="mono mt-3 text-xs text-mute">
          {s.executive_summary.counts.evidence} evidence items · {s.executive_summary.counts.realities} realities · {s.executive_summary.counts.surviving_realities} still compatible · {s.executive_summary.counts.critical_findings} critical findings
        </p>
      </Section>

      <Section index={2} title={t[1]}>
        <blockquote className="text-[22px] font-light leading-snug tracking-[-0.015em]">{s.claim.text}</blockquote>
        <p className="mt-2 text-sm text-dim">{s.claim.interpretation}</p>
      </Section>

      <Section index={3} title={t[2]}>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Field label="Window"><span className="mono text-xs">{utc(s.scope.window_start)} to {utc(s.scope.window_end)}</span></Field>
          <Field label="Assets">{s.scope.assets}</Field>
          <Field label="Dataset">{s.scope.dataset} (synthetic)</Field>
          <Field label="Objective">{s.scope.objective || "Not stated"}</Field>
        </dl>
      </Section>

      <Section index={4} title={t[3]}>
        <Rows head={["Source", "Mode", "Status"]} rows={s.sources.map((x: any) => [x.name, x.mode, x.status])} />
      </Section>

      <Section index={5} title={t[4]} kind="Observed">
        <p className="mb-3 text-[13px] text-dim">
          Reliability: {Object.entries(s.evidence_quality.by_reliability).map(([k, v]) => `${v} ${k}`).join(", ")}.
        </p>
        <Rows
          head={["ID", "Observation", "Reliability", "Relevance"]}
          rows={s.evidence_quality.items.map((e: any) => [<span key={e.ref} className="mono text-xs">{e.ref}</span>, e.observation, e.reliability, e.relevance])}
        />
      </Section>

      <Section index={6} title={t[5]} kind="Hypothesis">
        <p className="mb-3 text-[13px] text-dim">Generated explanations. None of these is an observed fact.</p>
        <div className="space-y-4">
          {s.realities.map((reality: any) => (
            <div key={reality.label}>
              <h3 className="text-[15px]">Reality {reality.label}: {reality.title}</h3>
              <p className="text-[13px] text-dim">{reality.statement}</p>
              <p className="mono mt-1 text-[11px] text-mute">
                {reality.compatibility} · for {reality.supporting.join(" ") || "none"} · against {reality.contradicting.join(" ") || "none"} · origin {reality.origin}
              </p>
            </div>
          ))}
        </div>
      </Section>

      <Section index={7} title={t[6]} kind="Analytical conclusion">
        <div className="space-y-3">
          {s.findings.map((finding: any) => (
            <div key={finding.title}>
              <h3 className="text-[15px]">{finding.title} <span className="mono ml-1 text-[11px] text-mute">{finding.severity}</span></h3>
              <p className="text-[13px] text-dim">{finding.body}</p>
            </div>
          ))}
        </div>
        <h3 className="label mb-2 mt-6">Limitations</h3>
        <ul className="space-y-1 text-[13px] text-dim">
          {s.limitations.map((limit: string) => <li key={limit}>{limit}</li>)}
        </ul>
      </Section>

      <Section index={8} title={t[7]} kind="Observed">
        {executed.length ? (
          <Rows head={["Procedure", "Status", "Value"]} rows={executed.map((p: any) => [p.title, p.status, `${p.information_gain_bits.toFixed(2)} bits`])} />
        ) : <p className="text-[13px] text-dim">No verification procedures had been executed when this report was generated.</p>}
      </Section>

      <Section index={9} title={t[8]} kind="Analytical conclusion">
        <div className="flex items-center gap-3">
          <AssessmentMark value={s.conclusion.assessment as Assessment} large />
          {s.conclusion.provisional && <Tag tone="warn">Provisional</Tag>}
        </div>
        <p className="mt-2 text-sm text-dim">{s.conclusion.rationale}</p>
      </Section>

      <Section index={10} title={t[9]}>
        {s.mitigations.length ? (
          <Rows head={["ID", "Action", "Priority", "Owner", "Approval"]} rows={s.mitigations.map((m: any) => [<span key={m.ref} className="mono text-xs">{m.ref}</span>, m.action, m.priority, m.owner, m.approval])} />
        ) : <p className="text-[13px] text-dim">No mitigations were recommended.</p>}
      </Section>

      <Section index={11} title={t[10]} kind="Observed">
        {s.verifications.length ? (
          <Rows head={["Action", "Result", "Summary"]} rows={s.verifications.map((v: any) => [v.remediation, v.passed ? "Passed" : v.recurrence ? "Recurrence" : "Failed", v.summary])} />
        ) : <p className="text-[13px] text-dim">No remediation had been verified when this report was generated.</p>}
      </Section>

      <Section index={12} title={t[11]}>
        <Rows
          head={["ID", "Tool", "Records", "SHA-256"]}
          rows={s.provenance.evidence.map((p: any) => [<span key={p.ref} className="mono text-xs">{p.ref}</span>, <span key="t" className="mono text-xs">{p.tool}</span>, p.record_count, <span key="s" className="mono text-[11px]">{(p.sha256 ?? "").slice(0, 16)}</span>])}
        />
        <p className="label mb-1 mt-6">Report snapshot SHA-256</p>
        <p className="mono break-all text-[11px] text-dim">{data.sha256}</p>
      </Section>
    </main>
  );
}
