"use client";

import {
  ChevronsUpDown,
  Database,
  FileText,
  LayoutDashboard,
  LogOut,
  Search,
  Settings,
  ShieldCheck,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, useApi } from "@/lib/api";
import type { DatasetInfo, Me, SourceView } from "@/lib/types";
import { Logo } from "./logo";
import { ErrorNote, Loading, ToastProvider } from "./ui";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/investigations", label: "Investigations", icon: Search },
  { href: "/assurance", label: "Assurance", icon: ShieldCheck },
  { href: "/sources", label: "Sources", icon: Database },
];

const SECONDARY_NAV = [
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/network", label: "Evidence Network", icon: Waypoints },
  { href: "/settings", label: "Settings", icon: Settings },
];

const isActive = (pathname: string, href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

const SessionContext = createContext<(Me & { can: (permission: string) => boolean }) | null>(null);

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside the app shell");
  return session;
}

function WorkspaceSelector({ name }: { name: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-2 rounded-md border border-line px-2.5 py-1.5 text-left text-[13px] text-dim transition-colors hover:text-fg"
      >
        <span className="truncate">{name}</span>
        <ChevronsUpDown size={13} className="shrink-0" aria-hidden />
      </button>
      {open && (
        <div className="absolute inset-x-0 top-full z-20 mt-1 rounded-md border border-line bg-raised p-3 text-[13px]">
          <p className="truncate">{name}</p>
          <p className="mt-1 text-xs text-dim">The only workspace in this installation. Adding workspaces isn&apos;t available yet.</p>
        </div>
      )}
    </div>
  );
}

function DataNotice({ dataset }: { dataset: DatasetInfo }) {
  const notice =
    dataset.origin === "demo"
      ? ["DEMONSTRATION WORKSPACE", "Synthetic data for a fictional company. No real systems are accessed or changed."]
      : dataset.data_class === "real"
        ? ["UPLOADED EVIDENCE", `${dataset.label}. NULL reads these files and does not change the systems behind them.`]
        : ["SYNTHETIC UPLOAD", `${dataset.label}. Test data. No real organization is being examined.`];
  return (
    <p className="no-print border-b border-line px-8 py-1.5 text-[11px] tracking-[0.04em] text-dim">
      <span className="mono">{notice[0]}</span>
      <span className="text-mute"> · {notice[1]}</span>
    </p>
  );
}

function ConnectionStatus({ me }: { me: Me }) {
  const { data } = useApi<{ sources: SourceView[] }>("/sources");
  const connected = data?.sources.filter((s) => s.status === "connected") ?? [];
  const mode = me.workspace.dataset.origin === "upload" ? "Uploaded files" : "Simulated";
  return (
    <Link href="/sources" className="block rounded-md px-2 py-2 text-xs text-dim transition-colors hover:bg-raised">
      <span className="flex items-center gap-2">
        <span aria-hidden className={`size-1.5 rounded-full ${connected.length ? "bg-ok" : "bg-mute"}`} />
        {data ? `${connected.length} of ${data.sources.length} sources connected` : "Checking sources"}
      </span>
      <span className="mt-0.5 block pl-3.5 text-mute">
        {mode} · {me.ai.active === "meta" ? me.ai.model_id : "Deterministic reasoning"}
      </span>
    </Link>
  );
}

function Sidebar({ me }: { me: Me }) {
  const pathname = usePathname();
  const router = useRouter();
  async function signOut() {
    await api("/auth/logout", { method: "POST" });
    router.push("/login");
  }
  return (
    <aside className="no-print sticky top-0 flex h-dvh w-[232px] shrink-0 flex-col border-r border-line bg-void px-3 py-5 max-lg:hidden">
      <Link href="/" className="mb-6 block px-2" aria-label="NULL home">
        <Logo size={24} />
      </Link>
      <div className="mb-5 px-0.5">
        <WorkspaceSelector name={me.workspace.name} />
      </div>
      <nav aria-label="Main" className="flex flex-1 flex-col">
        <div className="space-y-0.5">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = isActive(pathname, href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-sm transition-colors ${
                  active ? "bg-raised text-fg" : "text-dim hover:text-fg"
                }`}
              >
                <Icon size={15} strokeWidth={1.6} aria-hidden />
                {label}
              </Link>
            );
          })}
        </div>
        <div className="mt-auto space-y-0.5 pb-2">
          {SECONDARY_NAV.map(({ href, label, icon: Icon }) => {
            const active = isActive(pathname, href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-2.5 rounded-md px-2.5 py-[5px] text-[13px] transition-colors ${
                  active ? "bg-raised text-fg" : "text-mute hover:text-fg"
                }`}
              >
                <Icon size={14} strokeWidth={1.6} aria-hidden />
                {label}
              </Link>
            );
          })}
        </div>
      </nav>
      <ConnectionStatus me={me} />
      <div className="mt-2 flex items-center gap-2.5 border-t border-line px-2 pt-3">
        <span aria-hidden className="mono flex size-7 shrink-0 items-center justify-center rounded-full border border-line text-[11px] text-dim">
          {me.user.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px]">{me.user.name}</span>
          <span className="block truncate text-xs text-mute">{me.user.role}</span>
        </span>
        <button type="button" aria-label="Sign out" onClick={signOut} className="text-mute transition-colors hover:text-fg">
          <LogOut size={14} />
        </button>
      </div>
    </aside>
  );
}

function CompactNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="no-print sticky top-0 z-20 flex gap-1 overflow-x-auto border-b border-line bg-void px-3 py-2 lg:hidden">
      {[...NAV, ...SECONDARY_NAV].map(({ href, label }) => {
        const active = isActive(pathname, href);
        return (
          <Link key={href} href={href} className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[13px] ${active ? "bg-raised text-fg" : "text-dim"}`}>
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { data: me, error, reload } = useApi<Me>("/auth/me");
  const router = useRouter();
  useEffect(() => {
    if (error === "Not authenticated") router.replace("/login");
  }, [error, router]);

  if (error && error !== "Not authenticated") {
    return (
      <main className="mx-auto max-w-xl px-6 py-24">
        <ErrorNote message={`${error} Start the backend and try again.`} onRetry={reload} />
      </main>
    );
  }
  if (!me) {
    return (
      <main className="mx-auto max-w-4xl px-8 py-16">
        <Loading />
      </main>
    );
  }
  const session = { ...me, can: (permission: string) => me.user.permissions.includes(permission) };
  return (
    <SessionContext.Provider value={session}>
      <ToastProvider>
        <div className="flex min-h-dvh">
          <Sidebar me={me} />
          <div className="min-w-0 flex-1">
            <CompactNav />
            <DataNotice dataset={me.workspace.dataset} />
            {children}
          </div>
        </div>
      </ToastProvider>
    </SessionContext.Provider>
  );
}
