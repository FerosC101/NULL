"use client";

import { AlertTriangle, Check, Circle, Loader2, Minus, X } from "lucide-react";
import Link from "next/link";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ComponentProps,
  type ReactNode,
} from "react";
import type { Assessment } from "@/lib/types";
import { statusLabel } from "@/lib/format";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-fg text-void hover:bg-dim border-fg hover:border-dim",
  secondary: "bg-transparent text-fg border-line hover:bg-raised",
  ghost: "bg-transparent text-dim border-transparent hover:text-fg hover:bg-raised",
  danger: "bg-transparent text-bad border-line hover:border-bad",
};

const buttonClass = (variant: Variant, small?: boolean) =>
  `inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md border font-medium transition-colors duration-150 disabled:opacity-40 disabled:pointer-events-none ${
    small ? "h-7 px-2.5 text-[13px]" : "h-9 px-3.5 text-sm"
  } ${VARIANTS[variant]}`;

export function Button({
  variant = "secondary",
  small,
  busy,
  children,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; small?: boolean; busy?: boolean }) {
  return (
    <button type="button" {...props} disabled={props.disabled || busy} className={`${buttonClass(variant, small)} ${className}`}>
      {busy && <Loader2 size={14} className="animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({
  variant = "secondary",
  small,
  className = "",
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant; small?: boolean }) {
  return <Link {...props} className={`${buttonClass(variant, small)} ${className}`} />;
}

const ASSESSMENT_STYLE: Record<Assessment, { color: string; icon: ReactNode }> = {
  SUPPORTED: { color: "text-ok", icon: <Check size={12} strokeWidth={2.5} /> },
  CONTRADICTED: { color: "text-bad", icon: <X size={12} strokeWidth={2.5} /> },
  "PARTIALLY IDENTIFIED": { color: "text-warn", icon: <Minus size={12} strokeWidth={2.5} /> },
  UNDERDETERMINED: { color: "text-warn", icon: <Circle size={9} strokeWidth={2.5} /> },
  UNVERIFIED: { color: "text-dim", icon: <Circle size={9} strokeWidth={2.5} strokeDasharray="3 3" /> },
};

export function AssessmentMark({ value, large }: { value: Assessment; large?: boolean }) {
  const style = ASSESSMENT_STYLE[value];
  return (
    <span className={`mono inline-flex items-center gap-1.5 whitespace-nowrap ${style.color} ${large ? "text-xl tracking-wide" : "text-[11.5px] tracking-wide"}`}>
      <span aria-hidden className="inline-flex w-3 justify-center">
        {style.icon}
      </span>
      {value}
    </span>
  );
}

export function StatusText({ status }: { status: string }) {
  const running = status === "analyzing" || status === "running_checks" || status === "queued";
  const color = status === "failed" ? "text-bad" : status === "awaiting_approval" ? "text-warn" : "text-dim";
  return (
    <span className={`inline-flex items-center gap-1.5 text-[13px] ${color}`}>
      {running && <Loader2 size={12} className="animate-spin" aria-hidden />}
      {statusLabel(status)}
    </span>
  );
}

export function Tag({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "warn" | "bad" }) {
  const color = { neutral: "text-dim", ok: "text-ok", warn: "text-warn", bad: "text-bad" }[tone];
  return (
    <span className={`mono inline-flex h-5 items-center whitespace-nowrap rounded-sm border border-line px-1.5 text-[10.5px] uppercase tracking-[0.06em] ${color}`}>
      {children}
    </span>
  );
}

export function SectionHeader({
  label,
  title,
  description,
  action,
  id,
}: {
  label?: string;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  id?: string;
}) {
  return (
    <header id={id} className="mb-5 flex scroll-mt-20 flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        {label && <p className="label mb-1.5">{label}</p>}
        <h2 className="text-[22px] font-normal leading-tight tracking-[-0.015em]">{title}</h2>
        {description && <p className="mt-1.5 text-sm text-dim">{description}</p>}
      </div>
      {action}
    </header>
  );
}

export function PageHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <header className="mb-10 flex flex-wrap items-end justify-between gap-5">
      <div>
        <h1 className="text-[34px] font-light leading-[1.15] tracking-[-0.025em]">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-[15px] text-dim">{description}</p>}
      </div>
      {action}
    </header>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-lg border border-dashed border-line px-6 py-14 text-center">
      <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden className="mb-4">
        <circle cx="14" cy="14" r="13" stroke="#3A3A3A" strokeDasharray="2 3" />
      </svg>
      <p className="text-[15px]">{title}</p>
      {children && <p className="mt-1 max-w-md text-sm text-dim">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-4 rounded-md border border-line bg-surface px-4 py-3 text-sm">
      <span className="flex items-center gap-2.5 text-dim">
        <AlertTriangle size={15} className="shrink-0 text-bad" aria-hidden />
        {message}
      </span>
      {onRetry && (
        <Button small onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="space-y-3">
      <div className="skeleton h-9 w-72" />
      <div className="skeleton h-4 w-96 max-w-full" />
      <div className="pt-6" />
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="skeleton h-14 w-full" />
      ))}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  label,
  children,
  footer,
  drawer,
  width = 560,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  label?: string;
  children: ReactNode;
  footer?: ReactNode;
  drawer?: boolean;
  width?: number;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      data-drawer={drawer ? "" : undefined}
      onClose={onClose}
      onClick={(event) => event.target === ref.current && onClose()}
      style={{ width: `min(${width}px, calc(100vw - 32px))` }}
      aria-label={title}
    >
      {open && (
        <div className={`flex flex-col ${drawer ? "h-full" : "max-h-[86dvh]"}`}>
          <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
            <div>
              {label && <p className="label mb-0.5">{label}</p>}
              <h2 className="text-[17px] leading-snug">{title}</h2>
            </div>
            <button type="button" aria-label="Close" onClick={onClose} className="mt-0.5 text-dim transition-colors hover:text-fg">
              <X size={18} />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
          {footer && <div className="flex justify-end gap-2.5 border-t border-line px-6 py-3.5">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}

const ToastContext = createContext<(message: string, tone?: "ok" | "bad") => void>(() => {});

export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ message: string; tone: "ok" | "bad"; id: number } | null>(null);
  const show = useCallback((message: string, tone: "ok" | "bad" = "ok") => {
    const id = Date.now();
    setToast({ message, tone, id });
    setTimeout(() => setToast((current) => (current?.id === id ? null : current)), 4500);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2">
        {toast && (
          <div key={toast.id} className="rise flex max-w-lg items-center gap-2.5 rounded-md border border-line bg-raised px-4 py-2.5 text-sm">
            {toast.tone === "ok" ? (
              <Check size={14} className="shrink-0 text-ok" aria-hidden />
            ) : (
              <AlertTriangle size={14} className="shrink-0 text-bad" aria-hidden />
            )}
            {toast.message}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}

/** One line of a definition list, used wherever a record's fields are laid out. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="label mb-0.5">{label}</dt>
      <dd className="text-sm text-dim">{children}</dd>
    </div>
  );
}

export function FormField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] text-dim">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-dim">{hint}</span>}
    </label>
  );
}
