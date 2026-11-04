"use client";

import { ArrowLeft, ArrowRight, Check, Lock } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, ErrorNote, Field, FormField, Loading, Tag } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { dataClass, utc } from "@/lib/format";
import type { InvestigationOptions } from "@/lib/types";

const STEPS = ["Claim", "Scope", "Evidence", "Review"];

const EXAMPLES = [
  "No unauthorized access occurred during the last 24 hours.",
  "All endpoints were monitored during the window.",
  "MFA was enforced on all successful sign-ins.",
];

interface Compiled {
  kind: string;
  interpretation: string;
}

export default function NewInvestigationPage() {
  const router = useRouter();
  const { data: options, error: loadError } = useApi<InvestigationOptions>("/investigations/options");
  const [step, setStep] = useState(0);
  const [claim, setClaim] = useState("");
  const [compiled, setCompiled] = useState<Compiled | null>(null);
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [chosenDataset, setDataset] = useState<string | null>(null);
  const [hours, setHours] = useState(24);
  const [custom, setCustom] = useState(false);
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  const [assets, setAssets] = useState<string[]>([]);
  const [sources, setSources] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (claim.trim().length < 8) {
      setCompiled(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        setCompiled(await api<Compiled>("/investigations/compile", { body: { claim } }));
      } catch {
        setCompiled(null);
      }
    }, 280);
    return () => clearTimeout(timer);
  }, [claim]);

  const connected = options?.sources.filter((s) => s.status === "connected").map((s) => s.key) ?? [];
  const selected = sources ?? connected;
  const dataset = chosenDataset ?? options?.active_dataset ?? "A";
  const datasetInfo = options?.datasets.find((d) => d.key === dataset);
  const scopeReady = name.trim().length >= 2 && (!custom || (from !== "" && until !== ""));
  const canContinue = [claim.trim().length >= 8, scopeReady, selected.length > 0, true][step];

  function toggle<T>(list: T[], value: T) {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  function advance() {
    if (step === 0 && !name) setName(claim.trim().slice(0, 60).replace(/[.?!]$/, ""));
    setStep(step + 1);
  }

  async function begin() {
    setBusy(true);
    setError(null);
    try {
      const period = custom ? { window_start: `${from}:00Z`, window_end: `${until}:00Z` } : { window_hours: hours };
      const created = await api<{ id: string }>("/investigations", {
        body: { claim, name, objective, dataset, ...period, asset_classes: assets, source_keys: selected },
      });
      router.push(`/investigations/${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The investigation couldn't be started");
      setBusy(false);
    }
  }

  if (loadError) return <main className="mx-auto max-w-2xl px-8 py-16"><ErrorNote message={loadError} /></main>;
  if (!options) return <main className="mx-auto max-w-2xl px-8 py-16"><Loading /></main>;

  const windowLabel = custom ? `${from.replace("T", " ")} to ${until.replace("T", " ")} UTC` : options.windows.find((w) => w.hours === hours)?.label;
  const assetLabel = assets.length ? options.asset_classes.filter((a) => assets.includes(a.key)).map((a) => a.label).join(", ") : "All in-scope assets";

  return (
    <main className="mx-auto max-w-2xl px-8 pb-24 pt-10 max-sm:px-4">
      <Link href="/investigations" className="mb-8 inline-flex items-center gap-1.5 text-[13px] text-dim transition-colors hover:text-fg">
        <ArrowLeft size={14} aria-hidden /> Investigations
      </Link>
      <ol aria-label="Progress" className="mb-10 flex gap-6">
        {STEPS.map((label, index) => (
          <li key={label} aria-current={index === step ? "step" : undefined} className={`flex items-center gap-2 text-[13px] ${index === step ? "text-fg" : index < step ? "text-dim" : "text-mute"}`}>
            <span className="mono text-[11px]">{index < step ? <Check size={12} aria-hidden /> : index + 1}</span>
            {label}
          </li>
        ))}
      </ol>

      <div key={step} className="rise">
        {step === 0 && (
          <section>
            <h1 className="text-[30px] font-light leading-tight tracking-[-0.022em]">What is being claimed?</h1>
            <p className="mb-6 mt-2 text-[15px] text-dim">State the conclusion someone wants to rely on, in plain language.</p>
            <textarea
              aria-label="Claim"
              autoFocus
              rows={3}
              maxLength={1000}
              className="field !text-[18px] !font-light !leading-snug"
              placeholder="No unauthorized access occurred during the last 24 hours."
              value={claim}
              onChange={(event) => setClaim(event.target.value)}
            />
            <div className="mt-3 flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <button key={example} type="button" onClick={() => setClaim(example)} className="rounded-md border border-line px-2.5 py-1 text-xs text-dim transition-colors hover:text-fg">
                  {example}
                </button>
              ))}
            </div>
            {compiled && (
              <div className="rise mt-6 border-l border-line pl-4">
                <p className="label mb-1">How NULL reads this</p>
                <p className={`text-sm ${compiled.kind === "unsupported" ? "text-warn" : "text-dim"}`}>{compiled.interpretation}</p>
              </div>
            )}
          </section>
        )}

        {step === 1 && (
          <section className="space-y-5">
            <div>
              <h1 className="text-[30px] font-light leading-tight tracking-[-0.022em]">Define the scope</h1>
              <p className="mt-2 text-[15px] text-dim">A conclusion only holds inside the limits you set here.</p>
            </div>
            <FormField label="Investigation name">
              <input className="field" maxLength={200} value={name} onChange={(event) => setName(event.target.value)} />
            </FormField>
            <div className="grid gap-5 sm:grid-cols-2">
              <FormField label="Dataset" hint={datasetInfo?.origin === "demo" ? "Each snapshot has a different hidden outcome." : "Uploaded files. There is no answer key."}>
                <select className="field" value={dataset} onChange={(event) => setDataset(event.target.value)}>
                  {options.datasets.map((option) => <option key={option.key} value={option.key}>{option.label} ({dataClass(option.data_class)})</option>)}
                </select>
              </FormField>
              <FormField label="Time period" hint={datasetInfo ? `Records run from ${utc(datasetInfo.window_start)} to ${utc(datasetInfo.window_end)}.` : undefined}>
                <select className="field" value={custom ? "custom" : hours} onChange={(event) => {
                  setCustom(event.target.value === "custom");
                  if (event.target.value !== "custom") setHours(Number(event.target.value));
                }}>
                  {options.windows.map((option) => <option key={option.hours} value={option.hours}>{option.label}</option>)}
                  <option value="custom">Custom period</option>
                </select>
              </FormField>
            </div>
            {custom && (
              <div className="grid gap-5 sm:grid-cols-2">
                <FormField label="From (UTC, on the hour)">
                  <input type="datetime-local" step={3600} className="field" value={from} onChange={(event) => setFrom(event.target.value)} />
                </FormField>
                <FormField label="Until (UTC, on the hour)">
                  <input type="datetime-local" step={3600} className="field" value={until} onChange={(event) => setUntil(event.target.value)} />
                </FormField>
              </div>
            )}
            <fieldset>
              <legend className="mb-1.5 text-[13px] text-dim">Systems included</legend>
              <div className="flex flex-wrap gap-2">
                {options.asset_classes.map((asset) => (
                  <label key={asset.key} className={`cursor-pointer rounded-md border px-3 py-1.5 text-[13px] transition-colors ${assets.includes(asset.key) ? "border-fg" : "border-line text-dim hover:text-fg"}`}>
                    <input type="checkbox" className="sr-only" checked={assets.includes(asset.key)} onChange={() => setAssets(toggle(assets, asset.key))} />
                    {asset.label}
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-mute">{assets.length ? "Only records for these systems will be read." : "None selected means every in-scope asset."}</p>
            </fieldset>
            <FormField label="Investigation objective (optional)">
              <textarea className="field" rows={2} maxLength={2000} value={objective} onChange={(event) => setObjective(event.target.value)} />
            </FormField>
          </section>
        )}

        {step === 2 && (
          <section>
            <h1 className="text-[30px] font-light leading-tight tracking-[-0.022em]">Select evidence sources</h1>
            <p className="mb-6 mt-2 text-[15px] text-dim">NULL reads only what you select. Leaving out a source narrows what can be established.</p>
            <ul className="divide-y divide-line rounded-lg border border-line">
              {options.sources.map((source) => {
                const usable = source.status === "connected";
                return (
                  <li key={source.key}>
                    <label className={`flex items-center gap-3 px-4 py-3 transition-colors ${usable ? "cursor-pointer hover:bg-surface" : "opacity-55"}`}>
                      <input type="checkbox" className="accent-white" disabled={!usable} checked={selected.includes(source.key)} onChange={() => setSources(toggle(selected, source.key))} />
                      <span className="flex-1 text-sm">{source.name}</span>
                      {source.restricted && <span className="flex items-center gap-1 text-xs text-dim"><Lock size={11} aria-hidden /> Restricted</span>}
                      <Tag tone={usable ? "neutral" : "bad"}>{usable ? source.mode : "Disconnected"}</Tag>
                    </label>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {step === 3 && (
          <section>
            <h1 className="text-[30px] font-light leading-tight tracking-[-0.022em]">Review and begin</h1>
            <p className="mb-6 mt-2 text-[15px] text-dim">The first pass reads selected sources. Anything further waits for approval.</p>
            {error && <div className="mb-4"><ErrorNote message={error} /></div>}
            <blockquote className="border-l border-fg pl-4 text-[19px] font-light leading-snug">{claim}</blockquote>
            <dl className="mt-6 grid gap-5 sm:grid-cols-2">
              <Field label="Name">{name}</Field>
              <Field label="Period">{windowLabel}</Field>
              <Field label="Systems">{assetLabel}</Field>
              <Field label="Dataset">{datasetInfo?.label} ({dataClass(datasetInfo?.data_class)})</Field>
              <Field label="Sources">{options.sources.filter((s) => selected.includes(s.key)).map((s) => s.name).join(", ")}</Field>
              {objective && <Field label="Objective">{objective}</Field>}
            </dl>
          </section>
        )}
      </div>

      <div className="mt-10 flex justify-between">
        <Button variant="ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
        {step < 3 ? (
          <Button variant="primary" disabled={!canContinue} onClick={advance}>Continue <ArrowRight size={15} aria-hidden /></Button>
        ) : (
          <Button variant="primary" busy={busy} onClick={begin}>Begin investigation</Button>
        )}
      </div>
    </main>
  );
}
