"use client";

import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Logo } from "@/components/logo";
import { Button, ErrorNote, FormField } from "@/components/ui";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("ada@cobalt.example");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/login", { body: { email, password } });
      router.push("/");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Sign-in failed");
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-dvh lg:grid-cols-[1.25fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-line bg-void p-12 lg:flex lg:flex-col lg:justify-between">
        <Logo size={32} />
        <svg aria-hidden viewBox="0 0 700 700" fill="none" className="absolute -bottom-52 -right-40 w-[760px]">
          <circle cx="350" cy="350" r="348" stroke="#292929" />
          <circle cx="350" cy="350" r="228" stroke="#292929" />
          <circle cx="350" cy="350" r="108" stroke="#292929" />
          <circle cx="104" cy="104" r="5" fill="#fff" />
        </svg>
        <div className="relative max-w-lg">
          <h1 className="text-[44px] font-light leading-[1.12] tracking-[-0.03em]">
            Question Deeper.
            <br />
            Know Better.
          </h1>
          <p className="mt-5 max-w-md text-[15px] text-dim">
            NULL investigates whether a conclusion was ever justified by its evidence, and what remains unknown.
          </p>
        </div>
      </section>
      <section className="flex items-center justify-center px-6 py-16">
        <form onSubmit={submit} className="w-full max-w-sm space-y-5">
          <div className="lg:hidden">
            <Logo size={28} />
          </div>
          <div>
            <h2 className="text-[22px] font-normal tracking-[-0.015em]">Sign in</h2>
            <p className="mt-1 text-sm text-dim">Demonstration workspace with synthetic data.</p>
          </div>
          {error && <ErrorNote message={error} />}
          <FormField label="Email">
            <input className="field" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
          </FormField>
          <FormField label="Password" hint="Set by NULL_DEMO_PASSWORD in your .env file.">
            <input className="field" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </FormField>
          <Button type="submit" variant="primary" busy={busy} className="w-full">
            Sign in <ArrowRight size={15} aria-hidden />
          </Button>
        </form>
      </section>
    </main>
  );
}
