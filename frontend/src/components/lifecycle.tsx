"use client";

import { AlertTriangle, Check, Loader2, X } from "lucide-react";
import { useEffect, useRef } from "react";
import type { StageStatus, StageView } from "@/lib/types";

const WORDS: Record<StageStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  completed: "Completed",
  needs_attention: "Needs attention",
  blocked: "Blocked",
};

function StageMark({ status }: { status: StageStatus }) {
  const common = "flex size-[18px] shrink-0 items-center justify-center rounded-full border bg-base";
  if (status === "completed") return <span className={`${common} border-fg`}><Check size={10} strokeWidth={3} aria-hidden /></span>;
  if (status === "in_progress") return <span className={`${common} border-dim text-dim`}><Loader2 size={10} className="animate-spin" aria-hidden /></span>;
  if (status === "needs_attention") return <span className={`${common} border-warn text-warn`}><AlertTriangle size={9} strokeWidth={2.5} aria-hidden /></span>;
  if (status === "blocked") return <span className={`${common} border-bad text-bad`}><X size={10} strokeWidth={3} aria-hidden /></span>;
  return <span className={`${common} border-dashed border-mute`} />;
}

export function StageRail({ stages, active, onSelect }: { stages: StageView[]; active: string; onSelect: (key: string) => void }) {
  const rail = useRef<HTMLElement>(null);
  // On a narrow screen the rail scrolls, so the open stage is brought into view.
  useEffect(() => {
    const scroller = rail.current;
    const current = scroller?.querySelector<HTMLElement>('[aria-current="step"]');
    if (scroller && current) scroller.scrollLeft = current.offsetLeft - (scroller.clientWidth - current.offsetWidth) / 2;
  }, [active]);
  return (
    <nav ref={rail} aria-label="Investigation stages" className="relative -mx-1 overflow-x-auto">
      <ol className="flex min-w-[860px] px-1">
        {stages.map((stage) => {
          const on = stage.key === active;
          return (
            <li key={stage.key} className="min-w-0 flex-1 [position:static]">
              <button
                type="button"
                aria-current={on ? "step" : undefined}
                aria-label={`${stage.label}. ${WORDS[stage.status]}.${stage.summary ? ` ${stage.summary}.` : ""}`}
                onClick={() => onSelect(stage.key)}
                className={`relative block w-full border-b-2 pb-3 pr-3 pt-3 text-left transition-colors ${on ? "border-fg" : "border-transparent hover:border-line"}`}
              >
                <span aria-hidden className="absolute left-[18px] right-0 top-[20px] h-px bg-line" />
                <StageMark status={stage.status} />
                <span className={`mt-2 block text-[13px] ${on ? "text-fg" : stage.status === "not_started" ? "text-mute" : "text-dim"}`}>{stage.label}</span>
                <span className="mt-0.5 line-clamp-2 block min-h-8 text-[11px] leading-4 text-mute">{stage.summary}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

const TICK: Record<StageStatus, string> = {
  not_started: "bg-raised",
  in_progress: "bg-dim",
  completed: "bg-fg",
  needs_attention: "bg-warn",
  blocked: "bg-bad",
};

/** The same seven stages at list size. */
export function MiniRail({ stages }: { stages: StageView[] }) {
  const done = stages.filter((s) => s.status === "completed").length;
  const open = stages.filter((s) => s.status === "needs_attention" || s.status === "blocked").map((s) => s.label);
  return (
    <span role="img" aria-label={`${done} of ${stages.length} stages complete.${open.length ? ` Needs attention: ${open.join(", ")}.` : ""}`} className="flex w-[126px] shrink-0 gap-[3px]">
      {stages.map((stage) => <span key={stage.key} title={`${stage.label}: ${WORDS[stage.status]}`} className={`h-1 flex-1 rounded-[1px] ${TICK[stage.status]}`} />)}
    </span>
  );
}
