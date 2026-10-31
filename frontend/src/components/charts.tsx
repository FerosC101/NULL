"use client";

/** One tick per host, so a small gap stays visible instead of rounding away in a percentage. */
export function HostTicks({ total, flagged, label }: { total: number; flagged: string[]; label: string }) {
  const healthy = Math.max(total - flagged.length, 0);
  return (
    <div
      role="img"
      aria-label={`${label}: ${healthy} of ${total} hosts reporting. Not reporting: ${flagged.join(", ") || "none"}.`}
      className="flex h-5 items-stretch gap-px"
    >
      {Array.from({ length: healthy }, (_, index) => (
        <span key={index} className="min-w-px flex-1 bg-dim/70" />
      ))}
      {flagged.map((host) => (
        <span key={host} title={`${host}: no reporting agent`} className="min-w-px flex-1 bg-warn" />
      ))}
    </div>
  );
}

export interface Segment {
  label: string;
  value: number;
  /** Tailwind background class. Status colors are used only where the segment means that state. */
  color: string;
}

export function SegmentBar({ segments, label }: { segments: Segment[]; label: string }) {
  const present = segments.filter((s) => s.value > 0);
  const total = present.reduce((sum, s) => sum + s.value, 0);
  const description = present.map((s) => `${s.value} ${s.label}`).join(", ");
  return (
    <div>
      <div role="img" aria-label={`${label}: ${description || "none"}`} className="flex h-2 gap-0.5">
        {total === 0 && <span className="flex-1 rounded-[1px] bg-raised" />}
        {present.map((segment) => (
          <span
            key={segment.label}
            title={`${segment.value} ${segment.label}`}
            className={`rounded-[1px] ${segment.color}`}
            style={{ flexGrow: segment.value, flexBasis: 0 }}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-dim">
        {present.map((segment) => (
          <li key={segment.label} className="flex items-center gap-1.5">
            <span aria-hidden className={`size-1.5 rounded-[1px] ${segment.color}`} />
            <span className="mono">{segment.value}</span> {segment.label}
          </li>
        ))}
        {total === 0 && <li className="text-mute">Nothing recorded yet</li>}
      </ul>
    </div>
  );
}
