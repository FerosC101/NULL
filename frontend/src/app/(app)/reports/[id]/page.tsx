"use client";

import { ArrowLeft, FileDown, Printer, Table2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";
import { ChartFrame, CoverageMatrix, HostCoverage, TimeChart, type TimePoint } from "@/components/charts";
import { AssessmentMark, Button, ErrorNote, Field, Loading, Tag } from "@/components/ui";
import { PredictionMatrix } from "@/components/workspace/realities";
import { useApi } from "@/lib/api";
import { bytes, sentence, utc } from "@/lib/format";
import type { Assessment, Exhibits, ReportSummary, StageView } from "@/lib/types";
import { MiniRail } from "@/components/lifecycle";

/* eslint-disable @typescript-eslint/no-explicit-any */
interface FullReport extends ReportSummary {
  snapshot: any;
  sections: string[];
  versions: { id: string; ref: string; version: number; assessment: string; evidence: number; sha256: string; created_at: string }[];
}

type Kind = "Observed" | "Hypothesis" | "Analytical conclusion" | "Recommendation";

function Section({ index, title, kind, children }: { index: number; title: string; kind?: Kind; children: ReactNode }) {
  return (
    <section id={`section-${index}`} className="scroll-mt-6 border-t border-line py-8 first:border-t-0">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-[22px] font-light tracking-[-0.015em]">
          <span className="mono mr-3 text-xs text-mute">{String(index).padStart(2, "0")}</span>
          {title}
        </h2>
        {kind && <Tag tone={kind === "Hypothesis" ? "warn" : "neutral"}>{kind}</Tag>}
      </div>
      <div className="space-y-5">{children}</div>
    </section>
  );
}

function Sub({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-1.5 text-[15px]">{title}</h3>
      {children}
    </div>
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

const Mono = ({ children }: { children: ReactNode }) => <span className="mono whitespace-nowrap text-xs">{children}</span>;
const Text = ({ children }: { children: ReactNode }) => <p className="text-[13px] text-dim">{children}</p>;
const NotCaptured = () => <p className="text-[13px] text-mute">Not captured in this report version.</p>;
const refs = (values: string[]) => <Mono>{values.join("  ") || "None"}</Mono>;

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, reload } = useApi<FullReport>(`/reports/${id}`);
  if (error && !data) return <main className="mx-auto max-w-3xl px-8 py-12"><ErrorNote message={error} onRetry={reload} /></main>;
  if (!data) return <main className="mx-auto max-w-3xl px-8 py-12"><Loading rows={6} /></main>;
  const s = data.snapshot;
  const t = data.sections;
  const e = s.executive_summary;
  const exhibits: Exhibits | null = s.exhibits;
  const executed = s.procedures.filter((p: any) => p.status === "completed");
  const stopped = s.procedures.filter((p: any) => ["blocked", "failed", "rejected"].includes(p.status));
  const proposed = s.procedures.filter((p: any) => ["proposed", "approved", "running", "not_needed"].includes(p.status));
  const claimRealities = s.realities.filter((r: any) => r.claim_true);
  const support = [...new Set<string>(claimRealities.flatMap((r: any) => r.supporting))];
  const against = [...new Set<string>(claimRealities.flatMap((r: any) => r.contradicting))];
  const unknown: string[] = s.ledger.unknown ?? [];
  const assumed: string[] = s.ledger.assumed ?? [];
  const live = s.mitigations.filter((m: any) => m.approval !== "rejected");
  const open = live.filter((m: any) => m.verification !== "verified");
  const conflicts = s.findings.filter((f: any) => f.kind === "measurement_bias");
  const latest = data.versions[data.versions.length - 1];
  const previous = data.versions.find((v) => v.version === data.version - 1);
  const period = `${utc(s.scope.window_start)} to ${utc(s.scope.window_end)}`;
  const hasPredictions = s.realities.some((r: any) => r.predictions.length);

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
        <p className="label mb-2">Investigation report · {data.ref} · Version {data.version} of {data.versions.length}</p>
        <h1 className="text-[34px] font-light leading-[1.15] tracking-[-0.025em]">{s.investigation.name}</h1>
        <p className="mt-2 text-[13px] text-dim">{s.investigation.ref} · Generated {utc(data.created_at)} · {s.investigation.assignee}</p>
        <p className="mt-1 text-[13px] text-dim">{s.demo_notice}</p>
        {latest && latest.version !== data.version && (
          <p className="no-print mt-2 text-[13px] text-warn">A newer version exists. <Link href={`/reports/${latest.id}`} className="underline underline-offset-4">Open {latest.ref}</Link></p>
        )}
        {previous && previous.assessment !== data.assessment && (
          <p className="mt-2 text-[13px] text-dim">The conclusion changed from {previous.assessment} in {previous.ref}.</p>
        )}
      </header>

      <Section index={1} title={t[0]} kind="Analytical conclusion">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <AssessmentMark value={e.assessment as Assessment} large />
            {s.conclusion.provisional && <Tag tone="warn">Provisional</Tag>}
          </div>
          <p className="mt-2.5 text-[17px] font-light leading-snug">{e.rationale}</p>
        </div>
        {s.lifecycle.length > 0 && <MiniRail stages={s.lifecycle as StageView[]} />}
        <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          <Field label="Claim under review">{s.claim.text}</Field>
          {e.objective && <Field label="Investigation objective">{e.objective}</Field>}
          {e.key_finding && <Field label="Most important discovery">{e.key_finding.title}. {e.key_finding.body}</Field>}
          {e.uncertainty && <Field label="Main unresolved uncertainty">{e.uncertainty}</Field>}
          {e.next_action && <Field label="Recommended next action">{e.next_action.label}. {e.next_action.detail}</Field>}
        </dl>
        <p className="mono text-xs text-mute">
          {e.counts.evidence} evidence items · {e.counts.realities} explanations · {e.counts.surviving_realities} still compatible · {e.counts.critical_findings} critical findings · {e.counts.remediations} actions
        </p>
      </Section>

      <Section index={2} title={t[1]}>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Field label="Time period"><Mono>{period}</Mono></Field>
          <Field label="Assets">{s.scope.assets}</Field>
          <Field label="Dataset">{s.scope.dataset} (synthetic)</Field>
          <Field label="Objective">{s.scope.objective || "Not stated"}</Field>
        </dl>
        <Text>{s.claim.interpretation}</Text>
        <Sub title="Data sources examined"><Rows head={["Source", "Mode", "Status"]} rows={s.sources.map((x: any) => [x.name, x.mode, x.status])} /></Sub>
        {s.methodology && <Sub title="Methodology"><Text>{s.methodology}</Text></Sub>}
        <Sub title="Relevant limitations">
          <ul className="space-y-1 text-[13px] text-dim">{s.limitations.map((limit: string) => <li key={limit}>{limit}</li>)}</ul>
        </Sub>
      </Section>

      <Section index={3} title={t[2]} kind="Observed">
        <Text>Reliability: {Object.entries(s.evidence_quality.by_reliability).map(([k, v]) => `${v} ${k}`).join(", ")}.</Text>
        {exhibits ? (
          <>
            <ChartFrame title="Evidence coverage by source and hour" interpretation={exhibits.coverage_matrix.interpretation} period={`${utc(exhibits.coverage_matrix.window.start)} to ${utc(exhibits.coverage_matrix.window.end)}`}>
              <CoverageMatrix matrix={exhibits.coverage_matrix} />
            </ChartFrame>
            <ChartFrame title="What can see each host" interpretation={exhibits.host_coverage.unavailable ? undefined : `${exhibits.host_coverage.reporting} of ${exhibits.host_coverage.hosts} in-scope hosts have a reporting agent.`}>
              <HostCoverage data={exhibits.host_coverage} />
            </ChartFrame>
          </>
        ) : <NotCaptured />}
        <Sub title="Missing evidence"><Text>{unknown.length ? `Required and never observed: ${unknown.join(", ")}.` : "Nothing required remained unobserved."}</Text></Sub>
        {conflicts.length > 0 && <Sub title="Conflicting observations"><ul className="space-y-1 text-[13px] text-dim">{conflicts.map((f: any) => <li key={f.title}>{f.title}: {f.body}</li>)}</ul></Sub>}
      </Section>

      <Section index={4} title={t[3]} kind="Hypothesis">
        <Text>Generated explanations. None of these is an observed fact.</Text>
        {hasPredictions ? <PredictionMatrix realities={s.realities} observed={s.observations} /> : <NotCaptured />}
        <div className="space-y-4">
          {s.realities.map((reality: any) => (
            <div key={reality.label}>
              <h3 className="text-[15px]">Reality {reality.label}: {reality.title}</h3>
              <p className="text-[13px] text-dim">{reality.statement}</p>
              <p className="mono mt-1 text-[11px] text-mute">
                {reality.compatibility === "incompatible" ? "excluded" : reality.compatibility} · for {reality.supporting.join(" ") || "none"} · against {reality.contradicting.join(" ") || "none"} · origin {reality.origin}
              </p>
              {reality.assumptions.length > 0 && <p className="mt-0.5 text-xs text-dim">Assumes: {reality.assumptions.join(" ")}</p>}
            </div>
          ))}
        </div>
      </Section>

      <Section index={5} title={t[4]} kind="Observed">
        <Sub title="Tests performed">
          {executed.length ? (
            <div className="space-y-5">
              {executed.map((procedure: any) => (
                <div key={procedure.title}>
                  <h4 className="text-[13px] font-medium">{procedure.title}</h4>
                  <p className="mb-1.5 text-xs text-mute">{procedure.rationale || procedure.procedure}{procedure.decided_by ? ` Approved by ${procedure.decided_by}.` : ""}</p>
                  {procedure.results.length > 0 && (
                    <Rows
                      head={["Observable", "Expected", "Actual", "Ref"]}
                      rows={procedure.results.map((r: any) => [
                        r.label,
                        Object.entries(r.expected).map(([label, v]) => `${label}: ${v === "zero" ? "nothing" : v === "positive" ? "positive" : "no view"}`).join(", ") || "No prediction",
                        r.actual?.observation ?? "No result recorded",
                        <Mono key="ref">{r.actual?.ref ?? ""}</Mono>,
                      ])}
                    />
                  )}
                </div>
              ))}
            </div>
          ) : <Text>No test beyond the first pass had been executed when this report was generated.</Text>}
        </Sub>
        {exhibits?.egress.map((host) => {
          const points: TimePoint[] = host.points.map((p) => ({ iso: p.ts, value: p.bytes, expected: p.typical }));
          return (
            <ChartFrame
              key={host.host}
              title={`Hourly egress from ${host.host}`}
              interpretation={`Highest hour ${bytes(host.highest_bytes ?? 0)}, against a typical ${bytes(host.baseline_median_bytes ?? 0)}. ${host.explained_by_change ? "This falls inside an approved change." : "No approved change covers it."}`}
              period={period}
              source={exhibits.refs.egress ? `Evidence ${exhibits.refs.egress}` : undefined}
            >
              <TimeChart points={points} unit="Egress per hour, MB" observedName="Observed" expectedName="Typical for that hour" scale={1e6} events={host.events} formatValue={bytes} />
            </ChartFrame>
          );
        })}
        {stopped.length > 0 && <Sub title="Tests that did not complete"><Rows head={["Test", "Status", "Reason"]} rows={stopped.map((p: any) => [p.title, p.status, p.error || "Not recorded"])} /></Sub>}
        {proposed.length > 0 && <Sub title="Proposed tests, not executed"><Rows head={["Test", "Status", "Value"]} rows={proposed.map((p: any) => [p.title, sentence(p.status), `${p.information_gain_bits.toFixed(2)} bits`])} /></Sub>}
      </Section>

      <Section index={6} title={t[5]} kind="Analytical conclusion">
        <div>
          <AssessmentMark value={s.conclusion.assessment as Assessment} large />
          <p className="mt-2 text-[15px] text-dim">{s.conclusion.rationale}</p>
        </div>
        {claimRealities.length > 0 && (
          <dl className="grid gap-4 sm:grid-cols-2">
            <Field label="Evidence for the claim">{refs(support)}</Field>
            <Field label="Evidence against the claim">{refs(against)}</Field>
          </dl>
        )}
        {(s.ledger.inferred?.length ?? 0) > 0 && <Sub title="What the evidence establishes"><ul className="space-y-1 text-[13px] text-dim">{s.ledger.inferred.map((line: string) => <li key={line}>{line}</li>)}</ul></Sub>}
        <Sub title="Remaining uncertainty">
          <ul className="space-y-1 text-[13px] text-dim">
            {unknown.map((u) => <li key={u}>Not observed: {u}.</li>)}
            {assumed.map((a) => <li key={a}>Assumed, not tested: {a}</li>)}
            {!unknown.length && !assumed.length && <li>No required observation or assumption remains open.</li>}
          </ul>
        </Sub>
        <Sub title="Findings">
          {s.findings.length ? (
            <Rows head={["Severity", "Finding", "Evidence"]} rows={s.findings.map((f: any) => [sentence(f.severity), <span key="f"><span className="text-fg">{f.title}.</span> {f.body}</span>, refs(f.evidence)])} />
          ) : <Text>No weaknesses were identified in the evidence examined.</Text>}
        </Sub>
        <Sub title="Limitations"><ul className="space-y-1 text-[13px] text-dim">{s.limitations.map((limit: string) => <li key={limit}>{limit}</li>)}</ul></Sub>
      </Section>

      <Section index={7} title={t[6]} kind="Recommendation">
        {s.mitigations.length ? (
          <>
            {s.mitigations.some((m: any) => m.root_cause) && (
              <Sub title="Identified root causes"><ul className="space-y-1 text-[13px] text-dim">{[...new Set<string>(s.mitigations.map((m: any) => m.root_cause).filter(Boolean))].map((root) => <li key={root}>{root}</li>)}</ul></Sub>
            )}
            <Rows
              head={["ID", "Action", "Priority", "Owner", "Target", "Status"]}
              rows={s.mitigations.map((m: any) => [<Mono key="id">{m.ref}</Mono>, m.action, sentence(m.priority), m.owner, m.target_date ?? "Not set", `${sentence(m.approval)}, ${m.execution.replace("_", " ")}`])}
            />
          </>
        ) : <Text>No corrective actions were recommended.</Text>}
      </Section>

      <Section index={8} title={t[7]} kind="Observed">
        {live.length > 0 && <Sub title="Verification criteria"><Rows head={["ID", "Criteria", "Result"]} rows={live.map((m: any) => [<Mono key="id">{m.ref}</Mono>, m.criteria, sentence(m.verification)])} /></Sub>}
        <Sub title="Verification evidence">
          {s.verifications.length ? (
            <Rows head={["Action", "Time", "Result", "Evidence"]} rows={s.verifications.map((v: any) => [<Mono key="id">{v.remediation}</Mono>, <Mono key="at">{utc(v.at)}</Mono>, v.passed ? "Passed" : v.recurrence ? "Recurrence" : "Failed", v.summary])} />
          ) : <Text>No verification had run when this report was generated.</Text>}
        </Sub>
        <Sub title="Remaining risks">
          {open.length ? <ul className="space-y-1 text-[13px] text-dim">{open.map((m: any) => <li key={m.ref}>{m.ref}: {m.risk}</li>)}</ul> : <Text>No corrective action remains open.</Text>}
        </Sub>
      </Section>

      <Section index={9} title={t[8]}>
        <Sub title="Evidence references">
          <Rows head={["ID", "Observation", "Reliability", "Relevance"]} rows={s.evidence_quality.items.map((item: any) => [<Mono key="id">{item.ref}</Mono>, item.observation, item.reliability, item.relevance])} />
        </Sub>
        <Sub title="Assumptions"><Rows head={["Status", "Assumption", "Basis"]} rows={s.assumptions.map((a: any) => [sentence(a.status), a.text, a.basis || "Not tested"])} /></Sub>
        <Sub title="Statistical details">
          {exhibits?.signins ? (
            <ChartFrame title="Failed sign-ins per hour" interpretation={`${exhibits.signins.flagged_hours} of ${exhibits.signins.points.length} hours exceed the baseline at FDR 0.01.`} period={period}>
              <TimeChart bars points={exhibits.signins.points.map((p) => ({ iso: p.ts, value: p.failures, expected: p.expected, flagged: p.flagged }))} unit="Failed sign-ins per hour" observedName="Failed sign-ins" expectedName="Baseline for that hour" formatValue={(v) => v.toLocaleString()} />
            </ChartFrame>
          ) : <NotCaptured />}
        </Sub>
        <Sub title="Technical execution log">
          <Rows head={["Tool", "Role", "Status", "Records"]} rows={s.provenance.tool_executions.map((x: any) => [<Mono key="t">{x.tool}</Mono>, x.role, x.status, x.records_read.toLocaleString()])} />
        </Sub>
        <Sub title="Provenance">
          <Rows head={["ID", "Tool", "Records", "SHA-256"]} rows={s.provenance.evidence.map((p: any) => [<Mono key="id">{p.ref}</Mono>, <Mono key="t">{p.tool}</Mono>, p.record_count, <span key="s" className="mono text-[11px]">{(p.sha256 ?? "").slice(0, 16)}</span>])} />
        </Sub>
        <div>
          <p className="label mb-1">Report snapshot SHA-256</p>
          <p className="mono break-all text-[11px] text-dim">{data.sha256}</p>
        </div>
      </Section>
    </main>
  );
}
