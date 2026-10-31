"use client";

import { useEffect, useState } from "react";
import { useSession } from "@/components/shell";
import { Button, ErrorNote, Field, FormField, Loading, Modal, PageHeader, Tag, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { utc } from "@/lib/format";
import type { AiStatus } from "@/lib/types";

interface Member {
  id: string;
  email: string;
  name: string;
  title: string;
  role: string;
  is_active: boolean;
}

interface SettingsData {
  workspace: { id: string; name: string; is_demo: boolean; created_at: string };
  profile: Member;
  members: Member[];
  roles: Record<string, string[]>;
  ai: AiStatus;
  notifications: Record<string, boolean>;
  security: { session_hours?: number; separate_approver?: boolean };
  api: { base_path: string; docs_path: string; tokens_available: boolean };
}

const TABS = ["Workspace", "Profile", "Team", "Roles", "API", "AI", "Audit logs", "Notifications", "Security"] as const;
type Tab = (typeof TABS)[number];

function useSave() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function save(path: string, body: unknown, message: string, method = "PATCH") {
    setBusy(true);
    try {
      const result = await api(path, { method, body });
      toast(message);
      return result;
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "That couldn't be saved", "bad");
      return null;
    } finally {
      setBusy(false);
    }
  }
  return { busy, save };
}

function Panel({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="max-w-2xl">
      <h2 className="text-[22px] font-normal tracking-[-0.015em]">{title}</h2>
      {description && <p className="mt-1 text-sm text-dim">{description}</p>}
      <div className="mt-6">{children}</div>
    </section>
  );
}

function WorkspacePanel({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const { can } = useSession();
  const { busy, save } = useSave();
  const [name, setName] = useState(data.workspace.name);
  return (
    <Panel title="Workspace">
      <div className="space-y-4">
        <FormField label="Workspace name">
          <input className="field" disabled={!can("settings.manage")} value={name} onChange={(e) => setName(e.target.value)} />
        </FormField>
        <dl className="grid grid-cols-2 gap-4">
          <Field label="Type">{data.workspace.is_demo ? "Demonstration" : "Production"}</Field>
          <Field label="Created"><span className="mono text-xs">{utc(data.workspace.created_at)}</span></Field>
        </dl>
        {can("settings.manage") && <Button variant="primary" busy={busy} onClick={async () => { if (await save("/settings/workspace", { name }, "Workspace updated")) onSaved(); }}>Save</Button>}
      </div>
    </Panel>
  );
}

function ProfilePanel({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const { busy, save } = useSave();
  const [name, setName] = useState(data.profile.name);
  const [title, setTitle] = useState(data.profile.title);
  return (
    <Panel title="User profile">
      <div className="space-y-4">
        <FormField label="Name"><input className="field" value={name} onChange={(e) => setName(e.target.value)} /></FormField>
        <FormField label="Title"><input className="field" value={title} onChange={(e) => setTitle(e.target.value)} /></FormField>
        <dl className="grid grid-cols-2 gap-4">
          <Field label="Email">{data.profile.email}</Field>
          <Field label="Role">{data.profile.role}</Field>
        </dl>
        <Button variant="primary" busy={busy} onClick={async () => { if (await save("/settings/profile", { name, title }, "Profile updated")) onSaved(); }}>Save</Button>
      </div>
    </Panel>
  );
}

function TeamPanel({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const { can, user } = useSession();
  const { busy, save } = useSave();
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", role: "viewer", password: "" });
  const manage = can("settings.manage");
  async function add() {
    if (await save("/settings/members", form, `${form.name} added`, "POST")) {
      setAdding(false);
      setForm({ name: "", email: "", role: "viewer", password: "" });
      onSaved();
    }
  }
  return (
    <Panel title="Team management">
      <ul className="divide-y divide-line border-y border-line">
        {data.members.map((member) => (
          <li key={member.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
            <span className="min-w-0">
              <span className="block text-sm">{member.name}{!member.is_active && <span className="ml-2 text-xs text-mute">Inactive</span>}</span>
              <span className="block text-xs text-dim">{member.email}</span>
            </span>
            <select
              aria-label={`Role for ${member.name}`}
              className="field !w-auto !py-1 !text-[13px]"
              disabled={!manage || member.id === user.id}
              value={member.role}
              onChange={async (event) => { if (await save(`/settings/members/${member.id}`, { role: event.target.value, is_active: member.is_active }, "Role updated")) onSaved(); }}
            >
              {Object.keys(data.roles).map((role) => <option key={role} value={role}>{role}</option>)}
            </select>
          </li>
        ))}
      </ul>
      {manage && <Button className="mt-4" onClick={() => setAdding(true)}>Add member</Button>}
      {adding && (
        <Modal open title="Add a team member" onClose={() => setAdding(false)} footer={<><Button onClick={() => setAdding(false)}>Cancel</Button><Button variant="primary" busy={busy} onClick={add}>Add member</Button></>}>
          <div className="space-y-4">
            <FormField label="Name"><input className="field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></FormField>
            <FormField label="Email"><input className="field" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></FormField>
            <FormField label="Role">
              <select className="field" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {Object.keys(data.roles).map((role) => <option key={role} value={role}>{role}</option>)}
              </select>
            </FormField>
            <FormField label="Initial password" hint="At least 12 characters. Email invitations aren't available yet.">
              <input className="field" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </FormField>
          </div>
        </Modal>
      )}
    </Panel>
  );
}

function RolesPanel({ data }: { data: SettingsData }) {
  return (
    <Panel title="Roles and permissions" description="Investigators propose. Approvers authorize anything that reads restricted data or changes systems.">
      <dl className="divide-y divide-line border-y border-line">
        {Object.entries(data.roles).map(([role, permissions]) => (
          <div key={role} className="grid gap-2 py-3.5 sm:grid-cols-[130px_1fr]">
            <dt className="text-sm">{role}</dt>
            <dd className="flex flex-wrap gap-1.5">{permissions.map((p) => <Tag key={p}>{p}</Tag>)}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

function ApiPanel({ data }: { data: SettingsData }) {
  return (
    <Panel title="API configuration">
      <dl className="space-y-4">
        <Field label="Base path"><span className="mono text-xs">{data.api.base_path}</span></Field>
        <Field label="Reference"><a href={data.api.docs_path} className="underline decoration-line underline-offset-4 hover:text-fg">Interactive API documentation</a></Field>
        <Field label="Authentication">Session cookie, HTTP-only. Personal API tokens aren&apos;t available yet.</Field>
      </dl>
    </Panel>
  );
}

function AiPanel({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const { can } = useSession();
  const { busy, save } = useSave();
  const manage = can("settings.manage");
  const [mode, setMode] = useState(data.ai.reasoning_mode);
  const [model, setModel] = useState(data.ai.model_id);
  const [effort, setEffort] = useState(data.ai.reasoning_effort);
  const [test, setTest] = useState<{ ok: boolean; message: string; models: string[] } | null>(null);
  const [testing, setTesting] = useState(false);

  async function runTest() {
    setTesting(true);
    try {
      setTest(await api("/settings/ai/test", { method: "POST" }));
    } catch (cause) {
      setTest({ ok: false, message: cause instanceof Error ? cause.message : "The test failed", models: [] });
    } finally {
      setTesting(false);
    }
  }

  return (
    <Panel title="AI configuration" description="The model proposes. Deterministic validators decide. A model never sets a conclusion or a statistic.">
      <div className="mb-6 rounded-md border border-line p-4">
        <p className="flex items-center gap-2 text-sm">
          <span aria-hidden className={`size-1.5 rounded-full ${data.ai.active === "meta" ? "bg-ok" : "bg-warn"}`} />
          {data.ai.active === "meta" ? `Running on ${data.ai.model_id}` : "Running on deterministic reasoning"}
        </p>
        {data.ai.blocker && data.ai.reasoning_mode !== "deterministic" && <p className="mt-1 text-[13px] text-dim">{data.ai.blocker}</p>}
      </div>
      <dl className="mb-6 grid grid-cols-2 gap-4">
        <Field label="Provider">{data.ai.provider}</Field>
        <Field label="Endpoint"><span className="mono text-xs">{data.ai.base_url}</span></Field>
        <Field label="API key">{data.ai.key_configured ? "Configured on the server" : "Not configured"}</Field>
      </dl>
      <div className="space-y-4">
        <FormField label="Reasoning mode">
          <select className="field" disabled={!manage} value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="auto">Use the Meta model when configured</option>
            <option value="deterministic">Deterministic only</option>
          </select>
        </FormField>
        <FormField label="Model identifier" hint="Contributor models may use inputs for training, so they're blocked for evidence data.">
          <input className="field mono" disabled={!manage} list="models" placeholder="Choose after testing the connection" value={model} onChange={(e) => setModel(e.target.value.trim())} />
          <datalist id="models">{test?.models.map((m) => <option key={m} value={m} />)}</datalist>
        </FormField>
        <FormField label="Reasoning effort">
          <select className="field" disabled={!manage} value={effort} onChange={(e) => setEffort(e.target.value)}>
            {["minimal", "low", "medium", "high", "xhigh"].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </FormField>
        {test && <p className={`text-[13px] ${test.ok ? "text-ok" : "text-bad"}`}>{test.message}</p>}
        {manage && (
          <div className="flex gap-2">
            <Button variant="primary" busy={busy} onClick={async () => { if (await save("/settings/ai", { reasoning_mode: mode, model_id: model, reasoning_effort: effort }, "AI configuration saved")) onSaved(); }}>Save</Button>
            <Button busy={testing} onClick={runTest}>Test connection</Button>
          </div>
        )}
      </div>
    </Panel>
  );
}

function AuditPanel() {
  const { can } = useSession();
  const [action, setAction] = useState("");
  const allowed = can("audit.read");
  const { data, error } = useApi<{ id: string; at: string; actor: string; action: string; target: string; ip: string }[]>(
    allowed ? `/settings/audit?limit=200${action ? `&action=${encodeURIComponent(action)}` : ""}` : null,
  );
  if (!allowed) return <Panel title="Audit logs"><p className="text-sm text-dim">Your role doesn&apos;t include audit log access.</p></Panel>;
  return (
    <section>
      <h2 className="text-[22px] font-normal tracking-[-0.015em]">Audit logs</h2>
      <input aria-label="Filter by action" className="field mt-4 max-w-xs" placeholder="Filter by action" value={action} onChange={(e) => setAction(e.target.value)} />
      {error && <div className="mt-3"><ErrorNote message={error} /></div>}
      <div className="mt-3 overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[640px] text-left text-[13px]">
          <thead>
            <tr className="border-b border-line bg-surface">
              {["Time", "Actor", "Action", "Target"].map((heading) => <th key={heading} scope="col" className="label px-4 py-2 font-normal">{heading}</th>)}
            </tr>
          </thead>
          <tbody>
            {data?.map((row) => (
              <tr key={row.id} className="border-b border-line/60 last:border-b-0">
                <td className="mono whitespace-nowrap px-4 py-2 text-xs text-dim">{utc(row.at)}</td>
                <td className="px-4 py-2 text-dim">{row.actor}</td>
                <td className="mono px-4 py-2 text-xs">{row.action}</td>
                <td className="px-4 py-2 text-dim">{row.target}</td>
              </tr>
            ))}
            {data?.length === 0 && <tr><td colSpan={4} className="px-4 py-5 text-center text-dim">No entries.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const NOTIFICATIONS: [string, string][] = [
  ["critical_findings", "Critical findings"],
  ["approval_requests", "Approval requests"],
  ["verification_results", "Verification results"],
  ["weekly_digest", "Weekly digest"],
];

function NotificationsPanel({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const { can } = useSession();
  const { busy, save } = useSave();
  const [values, setValues] = useState(data.notifications);
  return (
    <Panel title="Notification preferences" description="Preferences are saved, but delivery channels aren't available yet. Nothing is sent.">
      <ul className="divide-y divide-line border-y border-line">
        {NOTIFICATIONS.map(([key, label]) => (
          <li key={key}>
            <label className="flex items-center justify-between py-3 text-sm">
              {label}
              <input type="checkbox" className="accent-white" disabled={!can("settings.manage")} checked={Boolean(values[key])} onChange={(e) => setValues({ ...values, [key]: e.target.checked })} />
            </label>
          </li>
        ))}
      </ul>
      {can("settings.manage") && <Button className="mt-4" variant="primary" busy={busy} onClick={async () => { if (await save("/settings/notifications", values, "Preferences saved")) onSaved(); }}>Save</Button>}
    </Panel>
  );
}

function SecurityPanel({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const { can } = useSession();
  const { busy, save } = useSave();
  const [separate, setSeparate] = useState(Boolean(data.security.separate_approver));
  return (
    <Panel title="Security settings">
      <dl className="mb-6 grid gap-4 sm:grid-cols-2">
        <Field label="Session length">{data.security.session_hours ?? 12} hours</Field>
        <Field label="Secrets">Server-side only. Never sent to the browser.</Field>
        <Field label="Check approval">Always required</Field>
        <Field label="Audit logging">Always on</Field>
      </dl>
      <label className="flex items-start gap-2.5 text-sm">
        <input type="checkbox" className="mt-1 accent-white" disabled={!can("settings.manage")} checked={separate} onChange={(e) => setSeparate(e.target.checked)} />
        <span>
          Require a different person to approve checks
          <span className="block text-[13px] text-dim">The person who started an investigation can&apos;t approve its checks.</span>
        </span>
      </label>
      {can("settings.manage") && <Button className="mt-4" variant="primary" busy={busy} onClick={async () => { if (await save("/settings/security", { separate_approver: separate }, "Security settings saved")) onSaved(); }}>Save</Button>}
    </Panel>
  );
}

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("Workspace");
  const { data, error, reload } = useApi<SettingsData>("/settings");
  useEffect(() => {
    const hash = decodeURIComponent(window.location.hash.slice(1));
    const match = TABS.find((t) => t.toLowerCase() === hash.toLowerCase());
    if (match) setTab(match);
  }, []);
  return (
    <main className="mx-auto max-w-[1180px] px-8 py-10 max-sm:px-4">
      <PageHeader title="Settings" />
      {error && !data && <ErrorNote message={error} onRetry={reload} />}
      {!data && !error && <Loading rows={3} />}
      {data && (
        <div className="grid gap-10 md:grid-cols-[170px_minmax(0,1fr)]">
          <nav aria-label="Settings sections" className="flex gap-1 overflow-x-auto md:flex-col md:gap-0.5">
            {TABS.map((item) => (
              <button
                key={item}
                type="button"
                aria-current={tab === item ? "page" : undefined}
                onClick={() => setTab(item)}
                className={`whitespace-nowrap rounded-md px-2.5 py-1.5 text-left text-sm transition-colors ${tab === item ? "bg-raised text-fg" : "text-dim hover:text-fg"}`}
              >
                {item}
              </button>
            ))}
          </nav>
          <div key={tab} className="rise min-w-0">
            {tab === "Workspace" && <WorkspacePanel data={data} onSaved={reload} />}
            {tab === "Profile" && <ProfilePanel data={data} onSaved={reload} />}
            {tab === "Team" && <TeamPanel data={data} onSaved={reload} />}
            {tab === "Roles" && <RolesPanel data={data} />}
            {tab === "API" && <ApiPanel data={data} />}
            {tab === "AI" && <AiPanel data={data} onSaved={reload} />}
            {tab === "Audit logs" && <AuditPanel />}
            {tab === "Notifications" && <NotificationsPanel data={data} onSaved={reload} />}
            {tab === "Security" && <SecurityPanel data={data} onSaved={reload} />}
          </div>
        </div>
      )}
    </main>
  );
}
