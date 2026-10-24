"use client";

import { SubmitEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { request } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const res = await request("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
    if (res.ok) return router.replace("/");
    setError(res.status === 429 ? "Too many attempts. Try again in a minute." : "Invalid username or password.");
    setBusy(false);
  }

  const field =
    "mt-1 w-full rounded-md border border-line bg-white px-3 py-2.5 text-base outline-none focus:border-accent";

  return (
    <main className="flex min-h-dvh items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border border-line bg-panel p-6 shadow-sm">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-muted">Private assistant running on your own machine.</p>
        <label className="mt-5 block text-sm font-medium">
          Username
          <input className={field} value={username} onChange={(e) => setUsername(e.target.value)}
                 autoComplete="username" autoCapitalize="none" required />
        </label>
        <label className="mt-4 block text-sm font-medium">
          Password
          <input className={field} type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 autoComplete="current-password" required />
        </label>
        {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
        <button disabled={busy}
                className="mt-5 w-full rounded-md bg-accent px-4 py-2.5 font-medium text-white disabled:opacity-60">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
