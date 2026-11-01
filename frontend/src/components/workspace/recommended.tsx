"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ChartFrame, TimeChart, timeTable, type TimePoint } from "@/components/charts";
import { useSession } from "@/components/shell";
import { Button, ErrorNote, Field, Modal, Tag, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { bytes, clock, utc } from "@/lib/format";
import type { CheckView, Exhibits, InvestigationDetail, RealityView } from "@/lib/types";
import { EvidenceRef, useInspect } from "./evidence";

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

const EXPECT: Record<string, string> = { positive: "Positive", zero: "Nothing", any: "No view" };

/** What each surviving explanation expects from a test, read from its declared predictions. */
function ExpectedTable({ check, realities }: { check: CheckView; realities: RealityView[] }) {
  const rows = check.observables
    .map((observable) => ({
      observable,
      cells: realities.map((r) => r.predictions.find((p) => p.observable === observable)),
    }))
    .filter((row) => row.cells.some(Boolean));
  if (!rows.length) return null;
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full min-w-[420px] text-left text-xs">
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className="label py-1 pr-3 font-normal">If it looks at</th>
            {realities.map((r) => <th key={r.label} scope="col" title={r.title} className="label w-20 py-1 pr-3 font-normal">Reality {r.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.observable} className="border-b border-line/50 last:border-b-0">
              <td className="py-1 pr-3 text-dim">{row.cells.find(Boolean)?.label}</td>
              {row.cells.map((cell, index) => (
                <td key={realities[index].label} className={`py-1 pr-3 ${cell?.expects === "positive" ? "text-fg" : "text-mute"}`}>{EXPECT[cell?.expects ?? "any"]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExecutedTest({ check, investigation, exhibits }: { check: CheckView; investigation: InvestigationDetail; exhibits: Exhibits | null }) {
  const inspect = useInspect();
  const results = check.observables
    .map((observable) => investigation.evidence.find((e) => e.primary && e.observable === observable))
    .filter((item): item is NonNullable<typeof item> => Boolean(item));
  const stopped = check.status === "blocked" || check.status === "failed" || check.status === "rejected";
  const series = check.tool === "test_host_egress" ? exhibits?.egress ?? [] : [];
  return (
    <li className="py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h4 className="text-[15px]">{check.title}</h4>
        <Tag tone={check.status === "completed" ? "ok" : stopped ? "bad" : "neutral"}>{check.status.replace("_", " ")}</Tag>
      </div>
      {check.decided_by && (
        <p className="mt-0.5 text-xs text-mute">{check.status === "rejected" ? "Rejected" : "Approved"} by {check.decided_by} · {check.information_gain_bits.toFixed(2)} bits expected</p>
      )}
      {check.error && <p className="mt-1 text-[13px] text-bad">{check.error}</p>}
      {results.length > 0 && (
        <ul className="mt-2.5 space-y-1.5">
          {results.map((item) => (
            <li key={item.ref} className="grid gap-x-3 text-[13px] sm:grid-cols-[72px_minmax(0,1fr)]">
              <EvidenceRef value={item.ref} />
              <span className="text-dim">{item.observation}</span>
            </li>
          ))}
        </ul>
      )}
      {series.map((host) => {
        const points: TimePoint[] = host.points.map((p) => ({ iso: p.ts, value: p.bytes, expected: p.typical }));
        const format = (value: number) => bytes(value);
        return (
          <div key={host.host} className="mt-5">
            <ChartFrame
              title={`Hourly egress from ${host.host}`}
              interpretation={`Highest hour ${bytes(host.highest_bytes ?? 0)} at ${clock(host.highest_ts ?? "")} UTC, against a typical ${bytes(host.baseline_median_bytes ?? 0)}. ${host.explained_by_change ? "This falls inside an approved change." : "No approved change covers it."}`}
              period={`${utc(investigation.scope.window_start)} to ${utc(investigation.scope.window_end)}`}
              source={exhibits?.refs.egress ? <span className="flex items-center gap-1.5">Source <EvidenceRef value={exhibits.refs.egress} /></span> : undefined}
              table={timeTable(points, "Observed", "Typical", format)}
            >
              <TimeChart
                points={points}
                unit="Egress per hour, MB"
                observedName="Observed"
                expectedName="Typical for that hour"
                scale={1e6}
                events={host.events}
                formatValue={format}
                onSelect={exhibits?.refs.egress ? () => inspect(exhibits.refs.egress!) : undefined}
              />
            </ChartFrame>
          </div>
        );
      })}
    </li>
  );
}

export function RecommendedInvestigation({ investigation, exhibits, onChanged }: { investigation: InvestigationDetail; exhibits: Exhibits | null; onChanged: () => void }) {
  const [reviewing, setReviewing] = useState(false);
  const open = investigation.checks.filter((c) => !TERMINAL.has(c.status) && c.status !== "running" && c.status !== "approved");
  const running = investigation.checks.filter((c) => c.status === "running" || c.status === "approved");
  const finished = investigation.checks.filter((c) => TERMINAL.has(c.status) && c.status !== "not_needed");
  const maxBits = Math.max(...investigation.checks.map((c) => c.information_gain_bits), 0.01);
  const awaiting = open.length > 0 && investigation.status === "awaiting_approval";
  const survivors = investigation.realities.filter((r) => r.compatibility !== "incompatible");

  useEffect(() => {
    if (investigation.status !== "awaiting_approval") setReviewing(false);
  }, [investigation.status]);

  if (!investigation.checks.length) {
    return <p className="text-sm text-dim">This claim has no further test to recommend. The first pass settled what the evidence could.</p>;
  }

  return (
    <div className="space-y-10">
      {awaiting && (
        <section aria-labelledby="proposed-heading">
          <p id="proposed-heading" className="label mb-2">Recommended, not yet run</p>
          <p className="max-w-3xl text-[20px] font-light leading-snug tracking-[-0.01em]">{headline(open)}</p>
          <dl className="mt-5 grid gap-5 md:grid-cols-2">
            <Field label="Why this matters">{open[0].rationale}</Field>
            <Field label="Uncertainty it addresses">
              {open[0].distinguishes.length ? `Separates ${open[0].distinguishes.map((l) => `Reality ${l}`).join(", ")}.` : "No surviving explanations."} {open[0].operational_impact}
            </Field>
          </dl>
          <ul className="mt-5 divide-y divide-line border-y border-line">
            {open.map((check) => (
              <li key={check.id} className="py-3">
                <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1">
                  <span className="min-w-0 flex-1 text-[13px]">
                    {check.title}
                    {check.error && <span className="mt-0.5 block text-xs text-bad">{check.error}</span>}
                  </span>
                  <GainBar bits={check.information_gain_bits} max={maxBits} />
                  <Tag tone={check.status === "blocked" || check.status === "failed" ? "bad" : "neutral"}>{check.status === "proposed" ? "Needs approval" : check.status}</Tag>
                </div>
                <ExpectedTable check={check} realities={survivors} />
                <p className="mt-1.5 text-xs text-mute">Reads: {check.requires_sources.join(", ")}</p>
              </li>
            ))}
          </ul>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="max-w-xl text-xs text-mute">
              Information value is expected entropy reduction across surviving realities, using a uniform prior and each
              reality&apos;s declared likelihoods. It ranks checks. It is not a probability of intrusion.
            </p>
            <Button variant="primary" onClick={() => setReviewing(true)}>Review Investigation</Button>
          </div>
        </section>
      )}
      {running.length > 0 && <p className="flex items-center gap-2 text-sm text-dim"><Loader2 size={14} className="animate-spin" aria-hidden /> Running {running.length} approved {running.length === 1 ? "test" : "tests"}.</p>}
      {finished.length > 0 && (
        <section aria-labelledby="executed-heading">
          <p id="executed-heading" className="label mb-1">Executed</p>
          <ul className="divide-y divide-line border-y border-line">
            {finished.map((check) => <ExecutedTest key={check.id} check={check} investigation={investigation} exhibits={exhibits} />)}
          </ul>
        </section>
      )}
      {!awaiting && !running.length && !finished.length && <p className="text-sm text-dim">No further test is recommended.</p>}
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
