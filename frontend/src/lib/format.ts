const dateTime = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

export function utc(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  return `${dateTime.format(new Date(value))} UTC`;
}

export function ago(value: string | null | undefined): string {
  if (!value) return "Never";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function duration(start: string | null, end: string | null): string {
  if (!start || !end) return "";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return ms < 1000 ? `${Math.max(ms, 1)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  analyzing: "Analyzing",
  awaiting_approval: "Awaiting approval",
  running_checks: "Running checks",
  concluded: "Concluded",
  failed: "Failed",
};

export const statusLabel = (status: string) => STATUS_LABELS[status] ?? status;

export const sentence = (value: string) => value.charAt(0).toUpperCase() + value.slice(1).replaceAll("_", " ");
