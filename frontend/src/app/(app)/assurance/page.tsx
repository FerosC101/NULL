"use client";

import { Check, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { HostTicks } from "@/components/charts";
import { useSession } from "@/components/shell";
import { Button, Empty, ErrorNote, Field, FormField, Loading, Modal, PageHeader, SectionHeader, Tag, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { sentence, utc } from "@/lib/format";
import type { AssuranceData, RemediationView } from "@/lib/types";

const PRIORITY_TONE: Record<string, "bad" | "warn" | "neutral"> = { critical: "bad", high: "warn", medium: "neutral", low: "neutral" };
const CLASS_LABEL: Record<string, string> = { workstation: "Workstations", server: "Servers", ot_gateway: "OT gateways" };

function Stepper({ remediation }: { remediation: RemediationView }) {
  const steps = [
    { label: "Approved", done: remediation.approval_status === "approved", failed: remediation.approval_status === "rejected" },
    { label: "Executed", done: remediation.execution_status === "executed", failed: false },
    {
      label: "Verified",
      done: remediation.verification_status === "verified",
      failed: remediation.verification_status === "failed" || remediation.verification_status === "recurred",
    },
  ];
  return (
    <ol aria-label="Progress" className="flex items-center gap-1.5">
      {steps.map((step, index) => (
        <li key={step.label} className="flex items-center gap-1.5 text-xs">
          {index > 0 && <span aria-hidden className="h-px w-3 bg-line" />}
          {step.failed ? (
            <X size={12} className="text-bad" aria-hidden />
          ) : (
            <span aria-hidden className={`flex size-3 items-center justify-center rounded-full border ${step.done ? "border-fg" : "border-line"}`}>
              {step.done && <span className="size-1 rounded-full bg-fg" />}
            </span>
          )}
          <span className={step.done ? "text-fg" : step.failed ? "text-bad" : "text-mute"}>{step.label}</span>
        </li>
      ))}
    </ol>
  );
}

function ModifyDialog({ remediation, onClose, onSaved }: { remediation: RemediationView; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [action, setAction] = useState(remediation.action);
  const [priority, setPriority] = useState(remediation.priority);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    setBusy(true);
    try {
      await api(`/assurance/remediations/${remediation.id}`, { method: "PATCH", body: { action, priority } });
      toast(`${remediation.ref} updated`);
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The change couldn't be saved");
      setBusy(false);
    }
  }
  return (
    <Modal open label={remediation.ref} title="Modify recommended action" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={save}>Save changes</Button></>}>
      {error && <div className="mb-4"><ErrorNote message={error} /></div>}
      <div className="space-y-4">
        <FormField label="Recommended action" hint={remediation.approval_status === "approved" ? "Changing this clears the existing approval." : undefined}>
          <textarea className="field" rows={4} value={action} onChange={(event) => setAction(event.target.value)} />
        </FormField>
        <FormField label="Priority">
          <select className="field" value={priority} onChange={(event) => setPriority(event.target.value)}>
            {["critical", "high", "medium", "low"].map((value) => <option key={value} value={value}>{sentence(value)}</option>)}
          </select>
        </FormField>
      </div>
    </Modal>
  );
}

function ExecuteDialog({ remediation, onClose, onDone }: { remediation: RemediationView; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    try {
      const result = await api<{ message: string }>(`/assurance/remediations/${remediation.id}/execute`, { body: { confirmed: true } });
      toast(result.message);
      onDone();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Execution failed");
      setBusy(false);
    }
  }
  return (
    <Modal open label={remediation.ref} title="Execute this action?" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={run}>Execute simulated change</Button></>}>
      {error && <div className="mb-4"><ErrorNote message={error} /></div>}
      <p className="text-[15px]">{remediation.action}</p>
      <p className="mt-3 text-sm text-dim">
        This uses the demonstration integration, which writes the records a real system would produce. No real system changes.
        The action stays unresolved until verification shows it worked.
      </p>
    </Modal>
  );
}

function RemediationRow({ remediation, onChanged }: { remediation: RemediationView; onChanged: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const [modifying, setModifying] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  async function act(path: string, success: string, body?: unknown) {
    setBusy(path);
    try {
      await api(`/assurance/remediations/${remediation.id}/${path}`, { method: "POST", body });
      toast(success);
      onChanged();
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "That action failed", "bad");
    } finally {
      setBusy(null);
    }
  }

  const executed = remediation.execution_status === "executed";
  const verified = remediation.verification_status === "verified";
  const pending = remediation.approval_status === "pending";
  const approved = remediation.approval_status === "approved";

  return (
    <li className="py-5">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="min-w-0 flex-1 basis-96">
          <p className="flex flex-wrap items-center gap-2">
            <span className="mono text-xs text-mute">{remediation.ref}</span>
            <Tag tone={PRIORITY_TONE[remediation.priority]}>{remediation.priority}</Tag>
            {remediation.investigation_ref && (
              <Link href={`/investigations/${remediation.investigation_id}`} className="mono text-[11px] text-dim underline decoration-line underline-offset-4 hover:text-fg">
                {remediation.investigation_ref}
              </Link>
            )}
          </p>
          <h3 className="mt-1.5 text-[15px] leading-snug">{remediation.action}</h3>
          <p className="mt-0.5 text-[13px] text-dim">{remediation.finding}</p>
        </div>
        <Stepper remediation={remediation} />
      </div>
      <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="mt-2 text-xs text-dim underline decoration-line underline-offset-4 hover:text-fg">
        {expanded ? "Hide details" : "Show details"}
      </button>
      {expanded && (
        <dl className="rise mt-3 grid gap-4 rounded-md border border-line bg-surface p-4 sm:grid-cols-2">
          <Field label="Root cause">{remediation.root_cause}</Field>
          <Field label="Risk addressed">{remediation.risk_addressed}</Field>
          <Field label="Responsible person">{remediation.owner.name}</Field>
          <Field label="Status">Approval {remediation.approval_status}, execution {remediation.execution_status.replace("_", " ")}, attempt {remediation.attempts}</Field>
          <div className="sm:col-span-2"><Field label="Verification criteria">{remediation.verification_criteria}</Field></div>
          {remediation.decision_note && <div className="sm:col-span-2"><Field label="Decision note">{remediation.decision_note}</Field></div>}
        </dl>
      )}
      {!verified && remediation.approval_status !== "rejected" && (
        <div className="mt-3 flex flex-wrap gap-2">
          {pending && can("remediations.approve") && <Button small variant="primary" busy={busy === "approve"} onClick={() => act("approve", `${remediation.ref} approved`, {})}>Approve</Button>}
          {pending && can("remediations.approve") && <Button small variant="danger" busy={busy === "reject"} onClick={() => act("reject", `${remediation.ref} rejected`, {})}>Reject</Button>}
          {!executed && can("remediations.write") && <Button small onClick={() => setModifying(true)}>Modify</Button>}
          {approved && can("remediations.execute") && <Button small variant={executed ? "secondary" : "primary"} onClick={() => setExecuting(true)}>{executed ? "Execute again" : "Execute"}</Button>}
          {executed && can("remediations.write") && <Button small variant="primary" busy={busy === "verify"} onClick={() => act("verify", `Verification finished for ${remediation.ref}`)}>Run verification</Button>}
          {pending && !can("remediations.approve") && <span className="text-xs text-dim">Awaiting a decision from an approver.</span>}
        </div>
      )}
      {remediation.runs[0] && !remediation.runs[0].passed && <p className="mt-2 text-[13px] text-bad">{remediation.runs[0].summary}</p>}
      {modifying && <ModifyDialog remediation={remediation} onClose={() => setModifying(false)} onSaved={() => { setModifying(false); onChanged(); }} />}
      {executing && <ExecuteDialog remediation={remediation} onClose={() => setExecuting(false)} onDone={() => { setExecuting(false); onChanged(); }} />}
    </li>
  );
}

function VerificationTable({ rows, onChanged }: { rows: RemediationView[]; onChanged: () => void }) {
  const { can } = useSession();
  const toast = useToast();

  async function run(remediation: RemediationView, path: string) {
    try {
      const result = await api<{ message?: string }>(`/assurance/remediations/${remediation.id}/${path}`, { method: "POST" });
      toast(result.message ?? `Verification finished for ${remediation.ref}`);
      onChanged();
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "That action failed", "bad");
    }
  }

  if (!rows.length) {
    return <Empty title="Nothing to verify yet">An action appears here once it has been executed. It can only be resolved by evidence.</Empty>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full min-w-[820px] text-left text-[13px]">
        <thead>
          <tr className="border-b border-line bg-surface">
            {["Original finding", "Corrective action", "Procedure", "Latest result", "Recurrence", ""].map((heading) => (
              <th key={heading} scope="col" className="label px-4 py-2 font-normal">{heading}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((remediation) => {
            const latest = remediation.runs[0];
            const everRecurred = remediation.runs.some((r) => r.recurrence);
            return (
              <tr key={remediation.id} className="border-b border-line/60 last:border-b-0">
                <td className="max-w-48 px-4 py-3 align-top text-dim">{remediation.finding}</td>
                <td className="max-w-64 px-4 py-3 align-top text-dim">{remediation.action}</td>
                <td className="mono px-4 py-3 align-top text-[11px] text-dim">{remediation.verification_procedure}</td>
                <td className="max-w-64 px-4 py-3 align-top">
                  {latest ? (
                    <>
                      <span className={`flex items-center gap-1.5 ${latest.passed ? "text-ok" : "text-bad"}`}>
                        {latest.passed ? <Check size={13} aria-hidden /> : <X size={13} aria-hidden />}
                        {latest.passed ? "Passed" : "Failed"}
                      </span>
                      <span className="mt-0.5 block text-xs text-dim">{latest.summary}</span>
                      <span className="mono mt-0.5 block text-[11px] text-mute">{utc(latest.created_at)}</span>
                    </>
                  ) : (
                    <span className="text-warn">Not yet verified</span>
                  )}
                </td>
                <td className="px-4 py-3 align-top">
                  {remediation.verification_status === "recurred" ? <Tag tone="bad">Recurred</Tag> : everRecurred ? <Tag tone="warn">Previously</Tag> : <span className="text-dim">None observed</span>}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right align-top">
                  <div className="flex flex-col items-end gap-1.5">
                    {can("remediations.write") && <Button small onClick={() => run(remediation, "verify")}>Run now</Button>}
                    {can("remediations.execute") && remediation.verification_status === "verified" && remediation.can_simulate_recurrence && (
                      <Button small variant="ghost" title="Demo control: makes the weakness return" onClick={() => run(remediation, "simulate-recurrence")}>Simulate recurrence</Button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function AssurancePage() {
  const { data, error, reload } = useApi<AssuranceData>("/assurance");
  if (error && !data) return <main className="mx-auto max-w-3xl px-8 py-12"><ErrorNote message={error} onRetry={reload} /></main>;
  if (!data) return <main className="mx-auto max-w-[1180px] px-8 py-12"><Loading rows={6} /></main>;

  const { preventive, remediations } = data;
  const coverage = preventive.coverage;
  const open = remediations.filter((r) => r.verification_status !== "verified");
  const executed = remediations.filter((r) => r.execution_status === "executed");
  const assumptions = preventive.unverified_assumptions;

  return (
    <main className="mx-auto max-w-[1180px] px-8 pb-24 pt-10 max-sm:px-4">
      <PageHeader title="Assurance" description="Prevent weak conclusions, fix what caused them, and keep proving the fix holds." />
      <nav aria-label="Sections" className="-mt-6 mb-10 flex gap-5 border-b border-line text-sm">
        {[["#preventive", "Preventive assurance"], ["#mitigation", "Mitigation management"], ["#verification", "Continuous verification"]].map(([href, label]) => (
          <a key={href} href={href} className="-mb-px border-b border-transparent pb-2.5 text-dim transition-colors hover:border-fg hover:text-fg">{label}</a>
        ))}
      </nav>

      <section className="mb-16">
        <SectionHeader id="preventive" title="Preventive assurance" description={`Measured from current records in Snapshot ${preventive.dataset}.`} />
        {preventive.unavailable.map((item) => <div key={item.key} className="mb-3"><ErrorNote message={`${item.key}: ${item.reason}. Part of this section can't be measured.`} /></div>)}
        {coverage && (
          <div className="rounded-lg border border-line">
            <div className="flex items-baseline justify-between gap-4 border-b border-line px-5 py-3.5">
              <h3 className="text-[15px]">Monitoring coverage</h3>
              <span className="mono text-xs text-dim">{coverage.reporting} of {coverage.hosts} hosts reporting</span>
            </div>
            <ul className="divide-y divide-line/60">
              {coverage.by_class.map((row) => (
                <li key={row.asset_class} className="grid items-center gap-x-6 gap-y-1 px-5 py-3 md:grid-cols-[130px_minmax(0,1fr)_110px]">
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
              <p className="border-t border-line px-5 py-2.5 text-xs text-dim">
                {coverage.never_enrolled.length} never enrolled. {coverage.stale.length} enrolled but silent, which an enrollment count would show as covered.
              </p>
            )}
          </div>
        )}
        <div className="mt-8 grid gap-8 md:grid-cols-2">
          <div>
            <h3 className="mb-2 text-[15px]">Disconnected data sources</h3>
            {preventive.disconnected_sources.length ? (
              <ul className="divide-y divide-line border-y border-line text-[13px]">
                {preventive.disconnected_sources.map((source) => (
                  <li key={source.key} className="flex justify-between py-2.5"><span>{source.name}</span><Tag tone="bad">Disconnected</Tag></li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-dim">Every source is connected.</p>}
          </div>
          <div>
            <h3 className="mb-2 text-[15px]">Evidence collection weaknesses</h3>
            {preventive.collection_weaknesses.length ? (
              <ul className="divide-y divide-line border-y border-line text-[13px]">
                {preventive.collection_weaknesses.map((gap) => (
                  <li key={gap.subnet} className="flex justify-between gap-3 py-2.5">
                    <span>{gap.subnet} network records</span>
                    <span className="mono text-xs text-dim">{gap.missing_hours}h missing from {utc(gap.first)}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-dim">No gaps in the current window.</p>}
          </div>
          <div>
            <h3 className="mb-2 text-[15px]">Unverified assumptions</h3>
            {assumptions.length ? (
              <ul className="divide-y divide-line border-y border-line text-[13px]">
                {assumptions.slice(0, 8).map((assumption) => (
                  <li key={`${assumption.investigation_id}-${assumption.text}`} className="flex items-start justify-between gap-3 py-2.5">
                    <span className="text-dim">{assumption.text}</span>
                    <Link href={`/investigations/${assumption.investigation_id}`} className="mono shrink-0 text-[11px] text-dim underline decoration-line underline-offset-4 hover:text-fg">
                      {assumption.investigation_ref}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-dim">None open.</p>}
          </div>
          <div>
            <h3 className="mb-2 text-[15px]">Emerging assurance risks</h3>
            {preventive.emerging_risks.length ? (
              <ul className="divide-y divide-line border-y border-line text-[13px]">
                {preventive.emerging_risks.map((risk) => (
                  <li key={risk.title} className="py-2.5"><span>{risk.title}</span><span className="mt-0.5 block text-dim">{risk.body}</span></li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-dim">None detected.</p>}
          </div>
        </div>
      </section>

      <section className="mb-16">
        <SectionHeader id="mitigation" title="Mitigation management" description="Every action needs an approval, an execution, and evidence that it worked." />
        {open.length ? (
          <ul className="divide-y divide-line border-y border-line">
            {open.map((remediation) => <RemediationRow key={remediation.id} remediation={remediation} onChanged={reload} />)}
          </ul>
        ) : (
          <Empty title="No open actions">Corrective actions appear here when an investigation finds a weakness.</Empty>
        )}
      </section>

      <section>
        <SectionHeader id="verification" title="Continuous verification" description="A remediation is resolved only when its verification procedure passes. Clicking a button can't resolve it." />
        <VerificationTable rows={executed} onChanged={reload} />
      </section>
    </main>
  );
}
