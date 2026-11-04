"use client";

import { Check, X } from "lucide-react";
import { useState } from "react";
import { RemediationRow, VerificationList } from "@/components/assurance/actions";
import { ChartFrame, CoverageMatrix, HostCoverage, matrixTable } from "@/components/charts";
import { AssessmentMark, Button, Field, Loading, Tag, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { dataClass, sentence, utc } from "@/lib/format";
import type { Exhibits, InvestigationDetail } from "@/lib/types";
import { EvidenceRef, EvidenceRefs, EvidenceTable, useInspect } from "./evidence";

const KINDS: Record<string, string> = {
  evidence_gap: "Evidence gap",
  unsupported_assumption: "Unsupported assumption",
  incomplete_observation: "Incomplete observation",
  measurement_bias: "Measurement bias",
};

const SEVERITY_DOT: Record<string, string> = { critical: "bg-bad", high: "bg-warn", medium: "bg-dim", low: "bg-mute" };

const LEDGER: { key: keyof InvestigationDetail["ledger"]; label: string }[] = [
  { key: "observed", label: "Observed" },
  { key: "inferred", label: "Inferred" },
  { key: "assumed", label: "Assumed" },
  { key: "unknown", label: "Unknown" },
  { key: "would_change", label: "Could change this" },
];

export function StageHeading({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <header className="mb-6">
      <h2 className="text-[22px] font-normal leading-tight tracking-[-0.015em]">{title}</h2>
      {children && <p className="mt-1 max-w-3xl text-sm text-dim">{children}</p>}
    </header>
  );
}

export function ClaimStage({ investigation }: { investigation: InvestigationDetail }) {
  const { scope, compiled_claim: compiled } = investigation;
  return (
    <section>
      <StageHeading title="What is being investigated" />
      <dl className="grid gap-x-10 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Time period"><span className="mono text-xs">{utc(scope.window_start)} to {utc(scope.window_end)}</span></Field>
        <Field label="Claim scope">{scope.assets_label}</Field>
        <Field label="Evidence sources">{investigation.source_keys.length} selected</Field>
        <Field label="Objective">{investigation.objective || "Not stated"}</Field>
        <Field label="Dataset">{investigation.dataset_label} ({dataClass(investigation.data_class)})</Field>
        <Field label="Investigator">{investigation.assignee}</Field>
      </dl>
      {compiled.notes?.length > 0 && (
        <ul className="mt-6 space-y-1 border-t border-line pt-4 text-[13px] text-dim">
          {compiled.notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      )}
    </section>
  );
}

export function EvidenceStage({ investigation, exhibits, loading }: { investigation: InvestigationDetail; exhibits: Exhibits | null; loading: boolean }) {
  const inspect = useInspect();
  const conflicts = investigation.findings.filter((f) => f.kind === "measurement_bias");
  const unknown = investigation.ledger.unknown ?? [];
  const hosts = exhibits?.host_coverage;
  return (
    <section className="space-y-10">
      <StageHeading title="What information is available" />
      {!exhibits && loading && <Loading rows={3} />}
      {exhibits && (
        <div className="-mt-3">
          <ChartFrame
            title="Evidence coverage by source and hour"
            interpretation={exhibits.coverage_matrix.interpretation}
            period={`${utc(exhibits.coverage_matrix.window.start)} to ${utc(exhibits.coverage_matrix.window.end)}. Endpoint records arrive in 4-hour batches.`}
            table={matrixTable(exhibits.coverage_matrix)}
          >
            <CoverageMatrix matrix={exhibits.coverage_matrix} onInspect={inspect} />
          </ChartFrame>
        </div>
      )}
      {hosts && (
        <ChartFrame
          title="What can see each host"
          interpretation={hosts.unavailable ? undefined : `${hosts.reporting} of ${hosts.hosts} hosts have a reporting agent. The ${hosts.unmonitored?.length ?? 0} without one are listed with the other evidence that reaches them.`}
          source={exhibits?.refs.coverage ? <span className="flex items-center gap-1.5">Source <EvidenceRef value={exhibits.refs.coverage} /></span> : undefined}
        >
          <HostCoverage data={hosts} />
        </ChartFrame>
      )}
      {(unknown.length > 0 || conflicts.length > 0) && (
        <div className="grid gap-8 md:grid-cols-2">
          {unknown.length > 0 && (
            <div>
              <h3 className="mb-2 text-[15px]">Missing</h3>
              <ul className="space-y-1 text-[13px] text-dim">{unknown.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          )}
          {conflicts.length > 0 && (
            <div>
              <h3 className="mb-2 text-[15px]">Conflicting or misleading</h3>
              <ul className="space-y-2 text-[13px] text-dim">
                {conflicts.map((finding) => <li key={finding.id}><span className="text-fg">{finding.title}.</span> {finding.body}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
      <div>
        <h3 className="mb-2.5 text-[15px]">Evidence items</h3>
        {investigation.evidence.length ? <EvidenceTable evidence={investigation.evidence} /> : <p className="text-sm text-dim">No evidence has been collected yet.</p>}
      </div>
    </section>
  );
}

function AnswerKey({ investigation }: { investigation: InvestigationDetail }) {
  const toast = useToast();
  const [truth, setTruth] = useState<{ narrative: string; matches: boolean; comparable: boolean; expected_assessment: string } | null>(null);
  async function reveal() {
    try {
      setTruth(await api(`/investigations/${investigation.id}/ground-truth`));
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "Answer key unavailable", "bad");
    }
  }
  if (!truth) return <Button small onClick={reveal}>Reveal demo answer key</Button>;
  return (
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
  );
}

export function FindingsStage({ investigation }: { investigation: InvestigationDetail }) {
  const provisional = investigation.status !== "concluded";
  const claim = investigation.realities.filter((r) => r.claim_true);
  const support = [...new Set(claim.flatMap((r) => r.supporting))];
  const against = [...new Set(claim.flatMap((r) => r.contradicting))];
  const { ledger } = investigation;
  const uncertain = [...(ledger.unknown ?? []).map((u) => `Not observed: ${u}`), ...(ledger.assumed ?? []).map((a) => `Assumed: ${a}`)];
  return (
    <section className="space-y-10">
      <header>
        <h2 className="sr-only">Investigation conclusion</h2>
        <div className="flex flex-wrap items-center gap-3">
          <AssessmentMark value={investigation.assessment} large />
          {provisional && <Tag tone="warn">Provisional</Tag>}
        </div>
        <p className="mt-3 max-w-3xl text-[17px] font-light leading-snug">{investigation.assessment_rationale}</p>
      </header>
      <dl className="grid gap-x-10 gap-y-7 md:grid-cols-2">
        <div>
          <dt className="mb-2 text-[15px]">What the evidence establishes</dt>
          {(ledger.inferred?.length ?? 0) > 0 ? ledger.inferred!.map((line) => <dd key={line} className="mb-1.5 text-[13px] text-dim">{line}</dd>) : <dd className="text-[13px] text-dim">Nothing has been established beyond the observations themselves.</dd>}
        </div>
        <div>
          <dt className="mb-2 text-[15px]">What remains uncertain</dt>
          {uncertain.length ? uncertain.map((line) => <dd key={line} className="mb-1.5 text-[13px] text-dim">{line}</dd>) : <dd className="text-[13px] text-dim">No required observation or assumption remains open.</dd>}
        </div>
        <div>
          <dt className="mb-2 text-[15px]">Why this conclusion</dt>
          <dd className="mb-2 flex items-baseline gap-3 text-[13px]"><span className="w-20 shrink-0 text-xs text-mute">For the claim</span><EvidenceRefs refs={support} /></dd>
          <dd className="mb-3 flex items-baseline gap-3 text-[13px]"><span className="w-20 shrink-0 text-xs text-mute">Against it</span><EvidenceRefs refs={against} /></dd>
          {investigation.assumptions.map((assumption) => (
            <dd key={assumption.key} className="mb-1.5 flex gap-2 text-[13px] text-dim">
              <span className={`mono mt-px w-9 shrink-0 text-[11px] ${assumption.status === "violated" ? "text-bad" : "text-mute"}`}>{assumption.status === "held" ? "HELD" : assumption.status === "violated" ? "FAIL" : "OPEN"}</span>
              {assumption.text}
            </dd>
          ))}
        </div>
        <div>
          <dt className="mb-2 text-[15px]">Limitations</dt>
          {investigation.limitations.length ? investigation.limitations.map((limit) => <dd key={limit} className="mb-1.5 text-[13px] text-dim">{limit}</dd>) : <dd className="text-[13px] text-dim">None recorded.</dd>}
        </div>
      </dl>
      <div>
        <h3 className="mb-2.5 text-[15px]">What NULL discovered</h3>
        {investigation.findings.length ? (
          <ul className="divide-y divide-line border-y border-line">
            {investigation.findings.map((finding) => (
              <li key={finding.id} className="grid gap-x-6 gap-y-1 py-3.5 md:grid-cols-[150px_minmax(0,1fr)]">
                <p className="flex items-center gap-2 self-start text-xs text-dim">
                  <span aria-hidden className={`size-1.5 shrink-0 rounded-full ${SEVERITY_DOT[finding.severity]}`} />
                  {KINDS[finding.kind] ?? sentence(finding.kind)}
                </p>
                <div>
                  <h4 className="text-[15px]">{finding.title}<span className="sr-only"> Severity {finding.severity}.</span></h4>
                  <p className="mt-1 text-[13px] text-dim">{finding.body}</p>
                  {finding.evidence_refs.length > 0 && <div className="mt-1.5"><EvidenceRefs refs={finding.evidence_refs} /></div>}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-dim">No weaknesses were identified in the evidence examined.</p>
        )}
      </div>
      <div>
        <h3 className="mb-2.5 text-[15px]">Knowledge ledger</h3>
        <dl className="grid grid-cols-2 gap-y-3 sm:grid-cols-5">
          {LEDGER.map(({ key, label }) => (
            <div key={key}>
              <dd className="mono text-xl font-light">{ledger[key]?.length ?? 0}</dd>
              <dt className="text-xs text-dim">{label}</dt>
            </div>
          ))}
        </dl>
      </div>
      {investigation.status === "concluded" && investigation.dataset_origin === "demo" && <AnswerKey investigation={investigation} />}
    </section>
  );
}

export function ActionsStage({ investigation, onChanged }: { investigation: InvestigationDetail; onChanged: () => void }) {
  const live = investigation.remediations.filter((r) => r.verification_status !== "verified");
  return (
    <section>
      <StageHeading title="Corrective actions">
        {investigation.remediations.length ? "Each needs an approval, an execution, and evidence that it worked." : undefined}
      </StageHeading>
      {live.length ? (
        <ul className="divide-y divide-line border-y border-line">
          {live.map((remediation) => <RemediationRow key={remediation.id} remediation={remediation} onChanged={onChanged} />)}
        </ul>
      ) : (
        <p className="text-sm text-dim">
          {investigation.remediations.length ? "Every action here has been verified." : investigation.status === "concluded" ? "This investigation recommended no corrective action." : "Actions are recommended once findings exist."}
        </p>
      )}
    </section>
  );
}

export function VerificationStage({ investigation, onChanged }: { investigation: InvestigationDetail; onChanged: () => void }) {
  const executed = investigation.remediations.filter((r) => r.execution_status === "executed");
  return (
    <section>
      <StageHeading title="Did the fix work">An action is resolved only when its verification procedure passes against records.</StageHeading>
      <VerificationList rows={executed} onChanged={onChanged} />
    </section>
  );
}
