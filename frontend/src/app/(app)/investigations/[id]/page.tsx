"use client";

import { ArrowLeft, ArrowRight, FileDown, Loader2, Waypoints } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { StageRail } from "@/components/lifecycle";
import { useSession } from "@/components/shell";
import { AssessmentMark, Button, ErrorNote, Loading, StatusText, useToast } from "@/components/ui";
import { AdvancedAnalysis } from "@/components/workspace/advanced";
import { EvidenceProvider, EvidenceRefs } from "@/components/workspace/evidence";
import { CompetingRealities } from "@/components/workspace/realities";
import { RecommendedInvestigation } from "@/components/workspace/recommended";
import { ActionsStage, ClaimStage, EvidenceStage, FindingsStage, StageHeading, VerificationStage } from "@/components/workspace/stages";
import { api, useApi } from "@/lib/api";
import { ago, dataClass } from "@/lib/format";
import type { Exhibits, InvestigationDetail, ReportSummary } from "@/lib/types";

const RUNNING = new Set(["queued", "analyzing", "running_checks"]);
const STAGE_KEYS = ["claim", "evidence", "explanations", "tests", "findings", "actions", "verification"];
// Links written before the stage layout still land in the right place.
const ANCHORS: Record<string, string> = { recommended: "tests", discovered: "findings" };

function stageFromHash() {
  const hash = window.location.hash.slice(1);
  const key = ANCHORS[hash] ?? hash;
  return STAGE_KEYS.includes(key) ? key : null;
}

function Summary({ investigation, onAct, busy, canReport }: { investigation: InvestigationDetail; onAct: () => void; busy: boolean; canReport: boolean }) {
  const { key_finding: finding, next_action: next, uncertainty } = investigation.lifecycle;
  const claim = investigation.realities.filter((r) => r.claim_true);
  const against = [...new Set(claim.flatMap((r) => r.contradicting))];
  const support = [...new Set(claim.flatMap((r) => r.supporting))];
  const survivors = investigation.realities.filter((r) => r.compatibility !== "incompatible");
  const actionable = next.kind === "open_stage" || (next.kind === "report" && canReport);
  return (
    <section aria-label="Summary" className="grid gap-px border-y border-line bg-line md:grid-cols-3">
      <div className="bg-base py-5 md:pr-6">
        <h2 className="label mb-2">What NULL found</h2>
        {finding ? (
          <>
            <p className="text-[17px] font-light leading-snug">{finding.title}</p>
            <p className="mt-1.5 line-clamp-3 text-[13px] text-dim">{finding.body}</p>
            <div className="mt-2"><EvidenceRefs refs={finding.evidence_refs} /></div>
          </>
        ) : (
          <p className="text-[15px] text-dim">{RUNNING.has(investigation.status) ? "Nothing yet. Analysis is running." : "No weakness was identified in the evidence examined."}</p>
        )}
      </div>
      <div className="bg-base py-5 md:px-6">
        <h2 className="label mb-2">Why this assessment</h2>
        {investigation.realities.length > 0 ? (
          <dl className="space-y-2 text-[13px]">
            <div className="flex items-baseline gap-3"><dt className="w-[90px] shrink-0 text-xs text-mute">Still possible</dt><dd>{survivors.length} of {investigation.realities.length} explanations</dd></div>
            <div className="flex items-baseline gap-3"><dt className="w-[90px] shrink-0 text-xs text-mute">For the claim</dt><dd><EvidenceRefs refs={support} /></dd></div>
            <div className="flex items-baseline gap-3"><dt className="w-[90px] shrink-0 text-xs text-mute">Against it</dt><dd><EvidenceRefs refs={against} /></dd></div>
          </dl>
        ) : <p className="text-[13px] text-dim">{investigation.assessment_rationale || "Not evaluated yet."}</p>}
        {uncertainty && <p className="mt-2.5 line-clamp-2 text-xs text-dim">{uncertainty}</p>}
      </div>
      <div className="bg-base py-5 md:pl-6">
        <h2 className="label mb-2">What should happen next</h2>
        <p className="text-[17px] font-light leading-snug">{next.label}</p>
        <p className="mt-1.5 line-clamp-2 text-[13px] text-dim">{next.detail}</p>
        {actionable && (
          <Button variant="primary" className="mt-3" busy={busy} onClick={onAct}>
            {next.kind === "report" ? "Generate report" : "Open"} <ArrowRight size={14} aria-hidden />
          </Button>
        )}
      </div>
    </section>
  );
}

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const [exporting, setExporting] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  const { data, error, reload } = useApi<InvestigationDetail>(`/investigations/${id}`, (d) => RUNNING.has(d.status));
  // Refetched whenever the investigation moves, so exhibits never lag what the page says.
  const { data: exhibits, loading: exhibitsLoading } = useApi<Exhibits>(data ? `/investigations/${id}/exhibits?at=${encodeURIComponent(data.updated_at)}` : null);

  useEffect(() => {
    const sync = () => setChosen(stageFromHash());
    sync();
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);

  const select = useCallback((key: string) => {
    window.history.pushState(null, "", `#${key}`);
    setChosen(key);
  }, []);

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

  const running = RUNNING.has(data.status);
  const stage = chosen ?? data.lifecycle.current;
  const next = data.lifecycle.next_action;

  return (
    <EvidenceProvider evidence={data.evidence} investigationId={data.id}>
      <main className="mx-auto max-w-[1160px] px-8 pb-24 pt-6 max-sm:px-4">
        <Link href="/investigations" className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-dim transition-colors hover:text-fg">
          <ArrowLeft size={14} aria-hidden /> Investigations
        </Link>

        <header className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3">
          <div className="min-w-0 flex-1 basis-96">
            <h1 className="text-[15px] leading-tight">{data.name}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-dim">
              <span className="mono text-xs">{data.ref}</span>
              <StatusText status={data.status} />
              <span>Updated {ago(data.updated_at)}</span>
              <span>{data.lifecycle.completed} of 7 stages complete</span>
              <span className="mono text-xs">{data.dataset_label} ({dataClass(data.data_class)})</span>
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href={`/network#${data.id}`} className="inline-flex h-9 items-center gap-2 rounded-md border border-line px-3.5 text-sm font-medium transition-colors hover:bg-raised">
              <Waypoints size={15} aria-hidden /> Evidence network
            </Link>
            {can("reports.write") && (
              <Button onClick={exportReport} busy={exporting} disabled={running}>
                <FileDown size={15} aria-hidden /> Export report
              </Button>
            )}
          </div>
        </header>

        {data.error && <div className="mt-4"><ErrorNote message={`This investigation stopped: ${data.error}`} /></div>}

        <section aria-labelledby="claim-heading" className="grid gap-x-10 gap-y-4 py-7 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div>
            <p id="claim-heading" className="label mb-2.5">Claim under review</p>
            <blockquote className="text-[30px] font-light leading-[1.2] tracking-[-0.022em] max-sm:text-[24px]">{data.claim}</blockquote>
          </div>
          <div className="lg:border-l lg:border-line lg:pl-8">
            <p className="label mb-2.5">Current assessment</p>
            {running ? (
              <p className="flex items-center gap-2 text-sm text-dim"><Loader2 size={14} className="animate-spin" aria-hidden /> Evaluating evidence</p>
            ) : (
              <AssessmentMark value={data.assessment} large />
            )}
            {data.status !== "concluded" && !running && <p className="mt-1.5 text-xs text-mute">Provisional until the investigation concludes.</p>}
          </div>
        </section>

        <Summary investigation={data} busy={exporting} canReport={can("reports.write")} onAct={() => (next.kind === "report" ? exportReport() : select(next.stage))} />

        <div className="mt-2 border-b border-line">
          <StageRail stages={data.lifecycle.stages} active={stage} onSelect={select} />
        </div>

        <div key={stage} className="rise py-9">
          {stage === "claim" && <ClaimStage investigation={data} />}
          {stage === "evidence" && <EvidenceStage investigation={data} exhibits={exhibits} loading={exhibitsLoading} />}
          {stage === "explanations" && (
            <section>
              <StageHeading title="Competing realities" />
              {data.realities.length ? <CompetingRealities investigation={data} /> : <p className="text-sm text-dim">{running ? "Explanations are being constructed." : "This claim has no competing explanations."}</p>}
            </section>
          )}
          {stage === "tests" && (
            <section>
              <StageHeading title="Tests" />
              <RecommendedInvestigation investigation={data} exhibits={exhibits} onChanged={refreshAfterDecision} />
            </section>
          )}
          {stage === "findings" && <FindingsStage investigation={data} />}
          {stage === "actions" && <ActionsStage investigation={data} onChanged={reload} />}
          {stage === "verification" && <VerificationStage investigation={data} onChanged={reload} />}
        </div>

        <AdvancedAnalysis investigation={data} exhibits={exhibits} />
      </main>
    </EvidenceProvider>
  );
}
