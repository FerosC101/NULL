"use client";

import { useEffect, useState } from "react";
import { useSession } from "@/components/shell";
import { Button, ErrorNote, Field, Modal, Tag, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { CheckView, InvestigationDetail } from "@/lib/types";

const TERMINAL = new Set(["completed", "rejected", "not_needed"]);

function GainBar({ bits, max }: { bits: number; max: number }) {
  return (
    <span className="flex items-center gap-2.5" title={`${bits.toFixed(2)} bits of an available ${max.toFixed(2)}`}>
      <span aria-hidden className="h-1 w-24 overflow-hidden rounded-[1px] bg-raised">
        <span className="block h-full bg-fg transition-[width] duration-300" style={{ width: `${max ? (bits / max) * 100 : 0}%` }} />
      </span>
      <span className="mono text-xs text-dim">{bits.toFixed(2)} bits</span>
    </span>
  );
}

function ReviewDialog({
  checks,
  investigation,
  maxBits,
  onClose,
  onDone,
}: {
  checks: CheckView[];
  investigation: InvestigationDetail;
  maxBits: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const { can } = useSession();
  const toast = useToast();
  const [selected, setSelected] = useState(new Set(checks.map((c) => c.id)));
  const [acknowledged, setAcknowledged] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canApprove = can("checks.approve");

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  async function decide(kind: "approve" | "reject") {
    setBusy(kind);
    setError(null);
    try {
      const ids = [...selected];
      await api(
        `/investigations/${investigation.id}/checks/${kind}`,
        { body: kind === "approve" ? { check_ids: ids, acknowledged } : { check_ids: ids, reason } },
      );
      toast(kind === "approve" ? `${ids.length} checks approved. Running now.` : "Checks rejected. The assessment stands as it was.");
      onDone();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The decision couldn't be recorded");
      setBusy(null);
    }
  }

  const permissions = [...new Set(checks.filter((c) => selected.has(c.id)).flatMap((c) => c.permissions))];
  return (
    <Modal
      open
      width={680}
      label={investigation.ref}
      title="Review investigation"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" busy={busy === "reject"} disabled={!canApprove || !selected.size || !!busy} onClick={() => decide("reject")}>
            Reject selected
          </Button>
          <Button variant="primary" busy={busy === "approve"} disabled={!canApprove || !selected.size || !acknowledged || !!busy} onClick={() => decide("approve")}>
            Approve and run
          </Button>
        </>
      }
    >
      {!canApprove && (
        <div className="mb-4 rounded-md border border-line bg-base px-4 py-3 text-sm text-dim">
          Your role can review these checks but not approve them. An approver or admin has to decide.
        </div>
      )}
      {error && <div className="mb-4"><ErrorNote message={error} /></div>}
      <p className="mb-4 text-sm text-dim">Nothing runs until you approve it. Choose which procedures may read this evidence.</p>
      <ul className="divide-y divide-line rounded-md border border-line">
        {checks.map((check) => (
          <li key={check.id}>
            <label className="flex cursor-pointer gap-3 px-4 py-3.5 transition-colors hover:bg-raised">
              <input type="checkbox" className="mt-1 accent-white" checked={selected.has(check.id)} onChange={() => toggle(check.id)} />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-sm">{check.title}</span>
                  <GainBar bits={check.information_gain_bits} max={maxBits} />
                </span>
                <span className="mt-1 block text-[13px] text-dim">{check.procedure}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <dl className="mt-5 space-y-3">
        <Field label="Required permissions">
          <span className="flex flex-wrap gap-1.5">
            {permissions.map((permission) => <Tag key={permission}>{permission}</Tag>)}
          </span>
        </Field>
        <Field label="Operational impact">All selected procedures are read-only. Reads of restricted sources are written to the audit log.</Field>
      </dl>
      <label className="mt-5 flex items-start gap-2.5 text-sm">
        <input type="checkbox" className="mt-1 accent-white" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
        I authorize these procedures to read the listed sources for this investigation.
      </label>
      <label className="mt-4 block">
        <span className="mb-1.5 block text-[13px] text-dim">Reason, if rejecting</span>
        <input className="field" maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
      </label>
    </Modal>
  );
}

function headline(checks: CheckView[]) {
  const reconcile = checks.some((c) => c.tool === "reconcile_inventory_coverage");
  const independent = checks.some((c) => c.tool === "inspect_independent_auth");
  if (reconcile && independent) {
    return "Compare the endpoint inventory against active monitoring coverage and inspect independent authentication records.";
  }
  return `${checks[0].title}.`;
}

export function RecommendedInvestigation({ investigation, onChanged }: { investigation: InvestigationDetail; onChanged: () => void }) {
  const [reviewing, setReviewing] = useState(false);
  const open = investigation.checks.filter((c) => !TERMINAL.has(c.status) && c.status !== "running" && c.status !== "approved");
  const running = investigation.checks.filter((c) => c.status === "running" || c.status === "approved");
  const finished = investigation.checks.filter((c) => TERMINAL.has(c.status) && c.status !== "not_needed");
  const allBits = investigation.checks.map((c) => c.information_gain_bits);
  const maxBits = Math.max(...allBits, 0.01);

  useEffect(() => {
    if (investigation.status !== "awaiting_approval") setReviewing(false);
  }, [investigation.status]);

  if (!investigation.checks.length) {
    return <p className="text-sm text-dim">This claim type has no further investigation to recommend. The first pass settled what the evidence could.</p>;
  }

  return (
    <div className="rounded-lg border border-line">
      {open.length > 0 && investigation.status === "awaiting_approval" ? (
        <div className="p-6">
          <p className="max-w-3xl text-[19px] font-light leading-snug tracking-[-0.01em]">{headline(open)}</p>
          <dl className="mt-5 grid gap-5 md:grid-cols-3">
            <Field label="Why this matters">{open[0].rationale}</Field>
            <Field label="Distinguishes">
              {open[0].distinguishes.length ? open[0].distinguishes.map((l) => `Reality ${l}`).join(", ") : "No surviving realities"}
            </Field>
            <Field label="Potential impact">{open[0].operational_impact}</Field>
          </dl>
        </div>
      ) : (
        <div className="p-6 text-sm text-dim">
          {running.length ? "Approved checks are running." : "No further investigation is recommended."}
        </div>
      )}
      <ul className="divide-y divide-line/60 border-t border-line">
        {[...open, ...running, ...finished].map((check) => (
          <li key={check.id} className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 px-6 py-3">
            <span className="min-w-0 flex-1 text-[13px]">
              {check.title}
              {check.error && <span className="mt-0.5 block text-xs text-bad">{check.error}</span>}
              {check.decided_by && (
                <span className="mt-0.5 block text-xs text-mute">
                  {check.status === "rejected" ? "Rejected" : "Approved"} by {check.decided_by}
                </span>
              )}
            </span>
            <GainBar bits={check.information_gain_bits} max={maxBits} />
            <Tag tone={check.status === "completed" ? "ok" : check.status === "blocked" || check.status === "failed" ? "bad" : "neutral"}>
              {check.status === "proposed" ? "Needs approval" : check.status.replace("_", " ")}
            </Tag>
          </li>
        ))}
      </ul>
      {open.length > 0 && investigation.status === "awaiting_approval" && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-6 py-3.5">
          <p className="max-w-xl text-xs text-dim">
            Information value is expected entropy reduction across surviving realities, using a uniform prior and each
            reality&apos;s declared likelihoods. It ranks checks. It is not a probability of intrusion.
          </p>
          <Button variant="primary" onClick={() => setReviewing(true)}>Review Investigation</Button>
        </div>
      )}
      {reviewing && (
        <ReviewDialog
          checks={open}
          investigation={investigation}
          maxBits={maxBits}
          onClose={() => setReviewing(false)}
          onDone={() => {
            setReviewing(false);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
