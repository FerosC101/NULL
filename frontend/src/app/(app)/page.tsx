"use client";

import { ArrowRight, ArrowUpRight, Check } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { MiniRail } from "@/components/lifecycle";
import { useSession } from "@/components/shell";
import { AssessmentMark, Empty, ErrorNote, LinkButton, Loading } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago, utc } from "@/lib/format";
import type { OverviewData } from "@/lib/types";

const SEVERITY_DOT: Record<string, string> = { critical: "bg-bad", high: "bg-warn" };
const FIRST_SHOWN = 5;

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function Attention({ items }: { items: OverviewData["attention"] }) {
  const [all, setAll] = useState(false);
  if (!items.length) return <p className="text-sm text-dim">Nothing needs attention right now.</p>;
  const shown = all ? items : items.slice(0, FIRST_SHOWN);
  return (
    <>
      <ul className="divide-y divide-line border-y border-line">
        {shown.map((item) => (
          <li key={`${item.kind}-${item.title}-${item.detail}`}>
            <Link href={item.href} className="group -mx-3 flex items-start gap-3 rounded-md px-3 py-3.5 transition-colors hover:bg-surface">
              <span aria-hidden className={`mt-[9px] size-1.5 shrink-0 rounded-full ${SEVERITY_DOT[item.severity] ?? "bg-dim"}`} />
              <span className="min-w-0 flex-1">
                <span className="block text-[15px] leading-snug">
                  {item.title}
                  <span className="sr-only"> ({item.severity})</span>
                </span>
                <span className="mt-0.5 line-clamp-1 block text-[13px] text-dim">{item.detail}</span>
              </span>
              <ArrowUpRight size={14} className="mt-1 shrink-0 text-mute transition-colors group-hover:text-fg" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
      {items.length > FIRST_SHOWN && (
        <button type="button" onClick={() => setAll(!all)} className="mt-2.5 text-[13px] text-dim underline decoration-line underline-offset-4 hover:text-fg">
          {all ? "Show fewer" : `Show all ${items.length}`}
        </button>
      )}
    </>
  );
}

export default function OverviewPage() {
  const { can } = useSession();
  const { data, error, reload } = useApi<OverviewData>("/overview");
  const [salutation, setSalutation] = useState("Good morning");
  useEffect(() => setSalutation(greeting()), []);

  if (error && !data) return <main className="mx-auto max-w-3xl px-8 py-12"><ErrorNote message={error} onRetry={reload} /></main>;
  if (!data) return <main className="mx-auto max-w-[1040px] px-8 py-12"><Loading rows={5} /></main>;

  const { coverage, disconnected_sources: disconnected } = data.assurance;

  return (
    <main className="mx-auto max-w-[1040px] px-8 pb-20 pt-12 max-sm:px-4">
      <header className="mb-11 flex flex-wrap items-end justify-between gap-5">
        <div>
          <h1 className="text-[42px] font-light leading-[1.1] tracking-[-0.03em] max-sm:text-[32px]">{salutation}. What do we know?</h1>
          <p className="mt-2.5 text-[15px] text-dim">
            {coverage ? `${coverage.reporting} of ${coverage.hosts} hosts reporting` : "Coverage source unavailable"}
            {disconnected.length > 0 && `, ${disconnected.length} ${disconnected.length === 1 ? "source" : "sources"} disconnected`}.
          </p>
        </div>
        {can("investigations.write") && (
          <LinkButton href="/investigations/new" variant="primary">Start Investigation <ArrowRight size={15} aria-hidden /></LinkButton>
        )}
      </header>

      <div className="space-y-12">
        <section aria-labelledby="attention-heading">
          <h2 id="attention-heading" className="mb-3 text-[19px] font-normal tracking-[-0.01em]">What needs attention</h2>
          <Attention items={data.attention} />
        </section>

        <section aria-labelledby="active-heading">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="active-heading" className="text-[19px] font-normal tracking-[-0.01em]">What we are investigating</h2>
            <Link href="/investigations" className="text-[13px] text-dim transition-colors hover:text-fg">View all</Link>
          </div>
          {data.active.length === 0 ? (
            <Empty title="Nothing is open">Start with a claim someone would like to rely on.</Empty>
          ) : (
            <ul className="divide-y divide-line border-y border-line">
              {data.active.map((investigation) => (
                <li key={investigation.id}>
                  <Link href={`/investigations/${investigation.id}`} className="-mx-3 grid gap-x-8 gap-y-2 rounded-md px-3 py-4 transition-colors hover:bg-surface md:grid-cols-[minmax(0,1fr)_260px]">
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className="text-[15px]">{investigation.name}</span>
                        <AssessmentMark value={investigation.assessment} />
                      </span>
                      <span className="mt-0.5 block truncate text-[13px] text-dim">{investigation.key_finding?.title ?? investigation.claim}</span>
                    </span>
                    <span className="min-w-0">
                      <MiniRail stages={investigation.stages} />
                      <span className="mt-2 block truncate text-[13px]">{investigation.next_action.label}</span>
                      <span className="block text-xs text-mute">Updated {ago(investigation.updated_at)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="resolved-heading">
          <h2 id="resolved-heading" className="mb-3 text-[19px] font-normal tracking-[-0.01em]">What we have resolved</h2>
          {data.resolved.length === 0 && data.concluded.length === 0 ? (
            <p className="text-sm text-dim">Nothing yet. A corrective action counts as resolved only after its verification passes.</p>
          ) : (
            <ul className="divide-y divide-line border-y border-line">
              {data.resolved.map((item) => (
                <li key={item.ref}>
                  <Link href={`/investigations/${item.investigation_id}#verification`} className="-mx-3 flex items-start gap-3 rounded-md px-3 py-3 transition-colors hover:bg-surface">
                    <Check size={14} className="mt-1 shrink-0 text-ok" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[15px] leading-snug">{item.finding}</span>
                      <span className="mt-0.5 block truncate text-[13px] text-dim">{item.summary || item.action}</span>
                    </span>
                    <span className="mono shrink-0 text-[11px] text-mute max-sm:hidden">{item.ref} · {utc(item.verified_at)}</span>
                  </Link>
                </li>
              ))}
              {data.concluded.map((investigation) => (
                <li key={investigation.id}>
                  <Link href={`/investigations/${investigation.id}`} className="-mx-3 flex items-center justify-between gap-4 rounded-md px-3 py-3 transition-colors hover:bg-surface">
                    <span className="min-w-0 truncate text-[15px]">{investigation.name}</span>
                    <AssessmentMark value={investigation.assessment} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}
