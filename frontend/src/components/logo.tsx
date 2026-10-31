/** Inline logo. Geometry matches scripts/brand.mjs. */
export function Mark({ size = 24, dot = 0.21, className }: { size?: number; dot?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden className={className}>
      <circle cx="32" cy="32" r="31" fill="#000" stroke="#3A3A3A" strokeWidth="1" />
      <circle cx="32" cy="32" r={31 * dot} fill="#fff" />
    </svg>
  );
}

export function Wordmark({ height = 12, className }: { height?: number; className?: string }) {
  return (
    <svg
      height={height}
      viewBox="-2 -2 123 28"
      fill="none"
      role="img"
      aria-label="NULL"
      className={className}
    >
      <path
        d="M0 24V0L18 24V0M36 0V15a9.5 9.5 0 0 0 19 0V0M73 0V24H87M105 0V24H119"
        stroke="currentColor"
        strokeWidth="2.7"
        strokeLinecap="square"
      />
    </svg>
  );
}

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-3 text-fg">
      <Mark size={size} />
      <Wordmark height={size * 0.46} />
    </span>
  );
}
