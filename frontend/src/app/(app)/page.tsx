"use client";

import { ArrowRight, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { HostTicks, SegmentBar } from "@/components/charts";
import { useSession } from "@/components/shell";
import { AssessmentMark, Empty, ErrorNote, LinkButton, Loading, StatusText } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago, statusLabel } from "@/lib/format";
import type { OverviewData } from "@/lib/types";

const METRICS: { key: string; label: string; href: string }[] = [
  { key: "active_investigations", label: "Active investigations", href: "/investigations" },
  { key: "unresolved_claims", label: "Unresolved claims", href: "/investigations" },
  { key: "critical_gaps", label: "Critical evidence gaps", href: "/assurance" },
  { key: "open_actions", label: "Open mitigation actions", href: "/assurance#mitigation" },
  { key: "verified_remediations", label: "Verified remediations", href: "/assurance#verification" },
];

const SEVERITY_DOT: Record<string, string> = { critical: "bg-bad", high: "bg-warn" };

const plural = (count: number, noun: string) => (count === 1 ? noun : `${noun}s`);

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export default function OverviewPage() {
  const { can } = useSession();
  const { data, error, reload } = useApi<OverviewData>("/overview");
  const [salutation, setSalutation] = useState("Good morning");
  useEffect(() => setSalutation(greeting()), []);

  if (error && !data) return <main className="mx-auto max-w-3xl px-8 py-12"><ErrorNote message={error} onRetry={reload} /></main>;
  if (!data) return <main className="mx-auto max-w-[1180px] px-8 py-12"><Loading rows={5} /></main>;

  const { assurance } = data;
  const coverage = assurance.coverage;
  const gapHosts = coverage ? [...coverage.never_enrolled, ...coverage.stale] : [];
  const statusOrder: [string, string][] = [
    ["awaiting_approval", "bg-warn"],
    ["analyzing", "bg-dim"],
    ["running_checks", "bg-dim"],
    ["concluded", "bg-fg"],
    ["failed", "bg-bad"],
  ];

  return (
    <main className="mx-auto max-w-[1180px] px-8 pb-20 pt-12 max-sm:px-4">
      <header className="mb-10 flex flex-wrap items-end justify-between gap-5">
        <div>
          <h1 className="text-[42px] font-light leading-[1.1] tracking-[-0.03em] max-sm:text-[32px]">{salutation}. What do we know?</h1>
          <p className="mt-2.5 text-[15px] text-dim">Your evidence environment, investigations, and unresolved uncertainties.</p>
        </div>
        {can("investigations.write") && (
          <LinkButton href="/investigations/new" variant="primary">Start Investigation <ArrowRight size={15} aria-hidden /></LinkButton>
        )}
      </header>

      <dl className="grid grid-cols-2 divide-line border-y border-line sm:grid-cols-3 lg:grid-cols-5 lg:divide-x">
        {METRICS.map(({ key, label, href }) => (
          <Link key={key} href={href} className="group px-4 py-5 transition-colors first:pl-0 hover:bg-surface lg:first:pl-4">
            <dd className="mono text-[30px] font-light leading-none">{data.metrics[key]}</dd>
            <dt className="mt-2 text-[13px] text-dim transition-colors group-hover:text-fg">{label}</dt>
          </Link>
        ))}
      </dl>

      <div className="mt-12 grid gap-12 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-12">
          <section aria-labelledby="assurance-heading">
            <div className="mb-5 flex items-baseline justify-between gap-4">
              <h2 id="assurance-heading" className="text-[19px] font-normal tracking-[-0.01em]">Assurance overview</h2>
              <span className="mono text-[11px] text-mute">Snapshot {assurance.dataset}</span>
            </div>
            <div className="space-y-6">
              <div>
                <div className="mb-2 flex items-baseline justify-between gap-3 text-[13px]">
                  <span>Evidence source coverage</span>
                  {coverage ? (
                    <span className="mono text-xs text-dim">{coverage.reporting} of {coverage.hosts} hosts reporting</span>
                  ) : (
                    <span className="text-xs text-bad">Coverage source unavailable</span>
                  )}
                </div>
                {coverage && <HostTicks total={coverage.hosts} flagged={gapHosts} label="Endpoint monitoring" />}
                {coverage && gapHosts.length > 0 && (
                  <p className="mt-2 flex items-center gap-1.5 text-xs text-dim">
                    <span aria-hidden className="size-1.5 rounded-[1px] bg-warn" /> {gapHosts.length} hosts without a reporting agent
                  </p>
                )}
              </div>
              <div>
                <div className="mb-2 flex items-baseline justify-between gap-3 text-[13px]">
                  <span>Unresolved monitoring gaps</span>
                  <span className="mono text-xs text-dim">{gapHosts.length + assurance.collection_weaknesses.length + assurance.disconnected_sources.length}</span>
                </div>
                <SegmentBar
                  label="Unresolved monitoring gaps"
                  segments={[
                    { label: plural(gapHosts.length, "unmonitored host"), value: gapHosts.length, color: "bg-warn" },
                    { label: plural(assurance.collection_weaknesses.length, "collection gap"), value: assurance.collection_weaknesses.length, color: "bg-dim" },
                    { label: plural(assurance.disconnected_sources.length, "disconnected source"), value: assurance.disconnected_sources.length, color: "bg-bad" },
                  ]}
                />
              </div>
              <div>
                <p className="mb-2 text-[13px]">Investigation status</p>
                <SegmentBar
                  label="Investigation status"
                  segments={statusOrder.map(([status, color]) => ({ label: statusLabel(status).toLowerCase(), value: assurance.status_counts[status] ?? 0, color }))}
                />
              </div>
              <div>
                <p className="mb-2 text-[13px]">Remediation progress</p>
                <SegmentBar
                  label="Remediation progress"
                  segments={[
                    { label: "verified", value: assurance.remediation.verified, color: "bg-ok" },
                    { label: "executed, unverified", value: assurance.remediation.executed, color: "bg-warn" },
                    { label: "approved", value: assurance.remediation.approved, color: "bg-dim" },
                    { label: "awaiting approval", value: assurance.remediation.pending, color: "bg-line" },
                  ]}
                />
              </div>
            </div>
          </section>

          <section aria-labelledby="recent-heading">
            <div className="mb-3 flex items-baseline justify-between">
              <h2 id="recent-heading" className="text-[19px] font-normal tracking-[-0.01em]">Recent investigations</h2>
              <Link href="/investigations" className="text-[13px] text-dim transition-colors hover:text-fg">View all</Link>
            </div>
            {data.recent.length === 0 ? (
              <Empty title="No investigations yet">Start with a claim someone would like to rely on.</Empty>
            ) : (
              <ul className="divide-y divide-line border-y border-line">
                {data.recent.map((investigation) => (
                  <li key={investigation.id}>
                    <Link href={`/investigations/${investigation.id}`} className="-mx-3 block rounded-md px-3 py-3.5 transition-colors hover:bg-surface">
                      <span className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                        <span className="text-[15px]">{investigation.name}</span>
                        <AssessmentMark value={investigation.assessment} />
                      </span>
                      <span className="mt-0.5 block truncate text-[13px] text-dim">{investigation.claim}</span>
                      <span className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-mute">
                        <StatusText status={investigation.status} />
                        <span>{ago(investigation.updated_at)}</span>
                        <span>{investigation.assignee}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <aside aria-labelledby="attention-heading">
          <h2 id="attention-heading" className="mb-3 text-[19px] font-normal tracking-[-0.01em]">Priority attention</h2>
          {data.attention.length === 0 ? (
            <p className="text-sm text-dim">Nothing needs attention right now.</p>
          ) : (
            <ul className="divide-y divide-line border-y border-line">
              {data.attention.map((item) => (
                <li key={`${item.kind}-${item.title}-${item.detail}`}>
                  <Link href={item.href} className="group -mx-3 flex items-start gap-3 rounded-md px-3 py-3 transition-colors hover:bg-surface">
                    <span aria-hidden className={`mt-[7px] size-1.5 shrink-0 rounded-full ${SEVERITY_DOT[item.severity] ?? "bg-dim"}`} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] leading-snug">
                        {item.title}
                        <span className="sr-only"> ({item.severity})</span>
                      </span>
                      <span className="mt-0.5 line-clamp-2 block text-xs text-dim">{item.detail}</span>
                    </span>
                    <ArrowUpRight size={14} className="mt-0.5 shrink-0 text-mute transition-colors group-hover:text-fg" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </main>
  );
}
