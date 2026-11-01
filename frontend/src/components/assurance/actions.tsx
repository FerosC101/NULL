"use client";

import { Check, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { RunStrip } from "@/components/charts";
import { useSession } from "@/components/shell";
import { Button, Empty, ErrorNote, Field, FormField, Modal, Tag, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { day, sentence, utc } from "@/lib/format";
import type { InvestigationOptions, RemediationView } from "@/lib/types";

const PRIORITY_TONE: Record<string, "bad" | "warn" | "neutral"> = { critical: "bad", high: "warn", medium: "neutral", low: "neutral" };

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
  const { data: options } = useApi<InvestigationOptions>("/investigations/options");
  const [action, setAction] = useState(remediation.action);
  const [priority, setPriority] = useState(remediation.priority);
  const [owner, setOwner] = useState(remediation.owner.id);
  const [target, setTarget] = useState(remediation.target_date ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    setBusy(true);
    try {
      await api(`/assurance/remediations/${remediation.id}`, {
        method: "PATCH",
        body: { action, priority, owner_id: owner, target_date: target || null },
      });
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
        <div className="grid gap-4 sm:grid-cols-3">
          <FormField label="Priority">
            <select className="field" value={priority} onChange={(event) => setPriority(event.target.value)}>
              {["critical", "high", "medium", "low"].map((value) => <option key={value} value={value}>{sentence(value)}</option>)}
            </select>
          </FormField>
          <FormField label="Responsible owner">
            <select className="field" value={owner} onChange={(event) => setOwner(event.target.value)}>
              {(options?.assignees ?? [remediation.owner]).map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
            </select>
          </FormField>
          <FormField label="Target date">
            <input type="date" className="field" value={target} onChange={(event) => setTarget(event.target.value)} />
          </FormField>
        </div>
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

export function RemediationRow({ remediation, onChanged }: { remediation: RemediationView; onChanged: () => void }) {
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
    <li className="py-4">
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
          <p className="mt-0.5 text-[13px] text-dim">
            {remediation.finding}
            <span className="text-mute"> · {remediation.owner.name} · {remediation.target_date ? `Due ${day(remediation.target_date)}` : "No target date"}</span>
          </p>
        </div>
        <Stepper remediation={remediation} />
      </div>
      {expanded && (
        <dl className="rise mt-3 grid gap-4 rounded-md border border-line bg-surface p-4 sm:grid-cols-2">
          <Field label="Root cause addressed">{remediation.root_cause}</Field>
          <Field label="Risk addressed">{remediation.risk_addressed}</Field>
          <Field label="Status">Approval {remediation.approval_status}, execution {remediation.execution_status.replace("_", " ")}, attempt {remediation.attempts}</Field>
          <Field label="Verification criteria">{remediation.verification_criteria}</Field>
          {remediation.decision_note && <div className="sm:col-span-2"><Field label="Decision note">{remediation.decision_note}</Field></div>}
        </dl>
      )}
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {!verified && remediation.approval_status !== "rejected" && (
          <>
            {pending && can("remediations.approve") && <Button small variant="primary" busy={busy === "approve"} onClick={() => act("approve", `${remediation.ref} approved`, {})}>Approve</Button>}
            {pending && can("remediations.approve") && <Button small variant="danger" busy={busy === "reject"} onClick={() => act("reject", `${remediation.ref} rejected`, {})}>Reject</Button>}
            {!executed && can("remediations.write") && <Button small onClick={() => setModifying(true)}>Modify</Button>}
            {approved && can("remediations.execute") && <Button small variant={executed ? "secondary" : "primary"} onClick={() => setExecuting(true)}>{executed ? "Execute again" : "Execute"}</Button>}
            {executed && can("remediations.write") && <Button small variant="primary" busy={busy === "verify"} onClick={() => act("verify", `Verification finished for ${remediation.ref}`)}>Run verification</Button>}
            {pending && !can("remediations.approve") && <span className="text-xs text-dim">Awaiting a decision from an approver.</span>}
          </>
        )}
        <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="text-xs text-dim underline decoration-line underline-offset-4 hover:text-fg">
          {expanded ? "Hide details" : "Show details"}
        </button>
      </div>
      {remediation.runs[0] && !remediation.runs[0].passed && <p className="mt-2 text-[13px] text-bad">{remediation.runs[0].summary}</p>}
      {modifying && <ModifyDialog remediation={remediation} onClose={() => setModifying(false)} onSaved={() => { setModifying(false); onChanged(); }} />}
      {executing && <ExecuteDialog remediation={remediation} onClose={() => setExecuting(false)} onDone={() => { setExecuting(false); onChanged(); }} />}
    </li>
  );
}

export function VerificationList({ rows, onChanged }: { rows: RemediationView[]; onChanged: () => void }) {
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
    <ul className="divide-y divide-line border-y border-line">
      {rows.map((remediation) => {
        const latest = remediation.runs[0];
        const everRecurred = remediation.runs.some((r) => r.recurrence);
        return (
          <li key={remediation.id} className="grid gap-x-8 gap-y-3 py-4 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_auto]">
            <div className="min-w-0">
              <p className="mono text-xs text-mute">{remediation.ref}</p>
              <h3 className="mt-1 text-[15px] leading-snug">{remediation.finding}</h3>
              <p className="mt-0.5 text-[13px] text-dim">{remediation.action}</p>
              <p className="mt-1.5 text-xs text-mute">Passes when: {remediation.verification_criteria}</p>
            </div>
            <div className="min-w-0">
              {latest ? (
                <>
                  <p className={`flex items-center gap-1.5 text-[13px] ${latest.passed ? "text-ok" : "text-bad"}`}>
                    {latest.passed ? <Check size={13} aria-hidden /> : <X size={13} aria-hidden />}
                    {latest.passed ? "Passed" : "Failed"}
                  </p>
                  <p className="mt-0.5 text-xs text-dim">{latest.summary}</p>
                  <p className="mono mt-0.5 text-[11px] text-mute">{utc(latest.created_at)}</p>
                </>
              ) : (
                <p className="text-[13px] text-warn">Executed, not yet verified</p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <RunStrip runs={remediation.runs} />
                {remediation.verification_status === "recurred" ? <Tag tone="bad">Recurred</Tag> : everRecurred ? <Tag tone="warn">Recurred before</Tag> : <span className="text-xs text-mute">No recurrence observed</span>}
              </div>
            </div>
            <div className="flex items-start gap-2 md:flex-col md:items-end">
              {can("remediations.write") && <Button small onClick={() => run(remediation, "verify")}>Run now</Button>}
              {can("remediations.execute") && remediation.verification_status === "verified" && remediation.can_simulate_recurrence && (
                <Button small variant="ghost" title="Demo control: makes the weakness return" onClick={() => run(remediation, "simulate-recurrence")}>Simulate recurrence</Button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
