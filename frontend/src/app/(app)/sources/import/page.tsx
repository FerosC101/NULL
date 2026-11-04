"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, ErrorNote, FormField, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import type { ImportView } from "@/lib/types";

const CLASSES = [
  { key: "real", label: "Real logs", hint: "Exports from systems you are responsible for. They stay on this server unless you allow the model below." },
  { key: "synthetic", label: "Test or synthetic data", hint: "Made-up data. It stays labelled as synthetic in investigations and reports." },
];

export default function NewImportPage() {
  const router = useRouter();
  const [label, setLabel] = useState("");
  const [dataClass, setDataClass] = useState("");
  const [allowModel, setAllowModel] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const created = await api<ImportView>("/imports", { body: { label, data_class: dataClass, allow_model: dataClass === "real" && allowModel } });
      router.push(`/sources/import/${created.key}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The upload couldn't be started");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-8 py-10 max-sm:px-4">
      <Link href="/sources" className="mb-8 inline-flex items-center gap-1.5 text-[13px] text-dim transition-colors hover:text-fg">
        <ArrowLeft size={14} aria-hidden /> Sources
      </Link>
      <PageHeader title="Upload evidence" description="Add exported logs as a dataset NULL can investigate. Files are kept exactly as received." />
      <div className="space-y-5">
        {error && <ErrorNote message={error} />}
        <FormField label="Dataset name">
          <input className="field" maxLength={120} value={label} placeholder="October sign-in review" onChange={(event) => setLabel(event.target.value)} />
        </FormField>
        <fieldset>
          <legend className="mb-1.5 text-[13px] text-dim">What is this data?</legend>
          <div className="space-y-2">
            {CLASSES.map((option) => (
              <label key={option.key} className={`block cursor-pointer rounded-md border px-3.5 py-2.5 transition-colors ${dataClass === option.key ? "border-fg" : "border-line hover:bg-surface"}`}>
                <input type="radio" name="data-class" className="sr-only" checked={dataClass === option.key} onChange={() => setDataClass(option.key)} />
                <span className="text-sm">{option.label}</span>
                <span className="mt-0.5 block text-xs text-dim">{option.hint}</span>
              </label>
            ))}
          </div>
        </fieldset>
        {dataClass === "real" && (
          <label className="flex items-start gap-2.5 text-[13px]">
            <input type="checkbox" className="mt-0.5 accent-white" checked={allowModel} onChange={(event) => setAllowModel(event.target.checked)} />
            <span>
              Let the Meta model read this evidence
              <span className="mt-0.5 block text-xs text-dim">Off, rule-based reasoning runs instead. On, summaries with hostnames, usernames and addresses go to Meta. Meta doesn&apos;t train on the Standard model, but its terms allow human review and name no fixed retention period. Only allow this if you have the right to share the data.</span>
            </span>
          </label>
        )}
        <Button variant="primary" busy={busy} disabled={label.trim().length < 2 || !dataClass} onClick={create}>Continue</Button>
      </div>
    </main>
  );
}
