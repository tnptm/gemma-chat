"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { request } from "@/lib/api";

type Config = {
  host: string; active_model: string; context_length: number; models_dir: string; keep_alive: string;
  num_parallel: number; max_loaded_models: number; flash_attention: boolean;
};
type Status = {
  running: boolean; managed: boolean; pid: number | null; version: string | null; binary_found: boolean;
  installed: { name: string; size: number }[];
  loaded: { name: string; size: number; size_vram: number }[];
  config: Config;
};

const gb = (n: number) => `${(n / 1e9).toFixed(1)} GB`;
const errText = (j: unknown) => {
  const o = (j ?? {}) as Record<string, unknown>;
  if (typeof o.detail === "string") return o.detail;
  const parts = Object.entries(o).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" ") : String(v)}`);
  return parts.join("; ") || "The request failed.";
};

export default function AdminPage() {
  const router = useRouter();
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState<Config | null>(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const [logs, setLogs] = useState("");

  const refresh = useCallback(async () => {
    const res = await request("/admin/ollama/status");
    if (res.status === 401 || res.status === 403) return router.replace("/"); // server-side check failed
    if (!res.ok) return;
    const s: Status = await res.json();
    setStatus(s);
    setDraft((d) => d ?? s.config);
  }, [router]);

  useEffect(() => {
    (async () => {
      const me = await request("/auth/me");
      if (!me.ok) return router.replace("/login");
      if (!(await me.json()).is_admin) return router.replace("/");
      refresh();
    })();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [router, refresh]);

  useEffect(() => {
    if (!showLogs) return;
    const load = async () => {
      const r = await request("/admin/ollama/logs");
      if (r.ok) setLogs((await r.json()).lines);
    };
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [showLogs]);

  async function act(label: string, path: string, body?: object) {
    setBusy(label);
    setMsg(null);
    const res = await request(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
    const j = await res.json().catch(() => ({}));
    setMsg(res.ok ? { ok: true, text: `${label}: done.` } : { ok: false, text: errText(j) });
    setBusy("");
    refresh();
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!draft) return;
    setBusy("Save");
    setMsg(null);
    const res = await request("/admin/ollama/config", { method: "PATCH", body: JSON.stringify(draft) });
    const j = await res.json().catch(() => ({}));
    if (res.ok) {
      setDraft(j);
      setMsg({ ok: true, text: status?.managed ? "Saved. Restart Ollama to apply the server settings." : "Saved." });
    } else setMsg({ ok: false, text: errText(j) });
    setBusy("");
    refresh();
  }

  if (!status || !draft) return <main className="p-6 text-muted">Loading…</main>;

  const set = <K extends keyof Config>(k: K, v: Config[K]) => setDraft({ ...draft, [k]: v });
  const input = "mt-1 w-full rounded-md border border-line bg-white px-3 py-2 text-base outline-none focus:border-accent";
  const btn = "rounded-md border border-line bg-white px-4 py-2 text-sm font-medium disabled:opacity-50";
  const loaded = new Map(status.loaded.map((m) => [m.name, m]));

  return (
    <main className="mx-auto max-w-3xl space-y-5 p-4 md:p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Ollama dashboard</h1>
        <nav className="flex gap-4 text-sm">
          <Link href="/admin/users" className="text-accent hover:underline">User management</Link>
          <Link href="/" className="text-accent hover:underline">Back to chat</Link>
        </nav>
      </header>

      {msg && <p role="status" className={`rounded-md border px-3 py-2 text-sm ${msg.ok ? "border-line bg-panel" : "border-red-300 bg-red-50 text-red-800"}`}>{msg.text}</p>}

      <section className="rounded-lg border border-line bg-panel p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-2 font-medium">
            <span className={`inline-block size-2.5 rounded-full ${status.running ? "bg-green-600" : "bg-muted"}`} aria-hidden />
            {status.running ? "Running" : "Stopped"}
          </span>
          {status.version && <span className="text-sm text-muted">version {status.version}</span>}
          {status.managed && <span className="text-sm text-muted">started here (pid {status.pid})</span>}
          <div className="ml-auto flex gap-2">
            <button className={btn} disabled={!!busy || status.running || !status.binary_found} onClick={() => act("Start", "/admin/ollama/start")}>
              {busy === "Start" ? "Starting…" : "Start"}
            </button>
            <button className={btn} disabled={!!busy || !status.managed} onClick={() => act("Restart", "/admin/ollama/restart")}>
              {busy === "Restart" ? "Restarting…" : "Restart"}
            </button>
            <button className={btn} disabled={!!busy || !status.managed} onClick={() => act("Stop", "/admin/ollama/stop")}>
              {busy === "Stop" ? "Stopping…" : "Stop"}
            </button>
          </div>
        </div>
        {!status.binary_found && <p className="mt-3 text-sm text-red-800">The ollama executable was not found. Set OLLAMA_BIN in backend/.env.</p>}
        {status.running && !status.managed && (
          <p className="mt-3 text-sm text-muted">Ollama is running outside this dashboard (for example as a system service), so it cannot be stopped or restarted from here.</p>
        )}
      </section>

      <section className="rounded-lg border border-line bg-panel p-4">
        <h2 className="font-medium">Models</h2>
        {!status.running ? (
          <p className="mt-2 text-sm text-muted">Start Ollama to see installed models.</p>
        ) : status.installed.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No models installed. Run “ollama pull &lt;model&gt;” in a terminal.</p>
        ) : (
          <ul className="mt-2 divide-y divide-line">
            {status.installed.map((m) => {
              const l = loaded.get(m.name);
              return (
                <li key={m.name} className="flex flex-wrap items-center gap-3 py-2.5">
                  <span className="min-w-0 flex-1 truncate">{m.name}</span>
                  <span className="text-sm text-muted">{gb(m.size)}</span>
                  {l && <span className="text-sm">in memory ({gb(l.size_vram)} on GPU)</span>}
                  <button className={btn} disabled={!!busy}
                          onClick={() => act(l ? "Unload" : "Load", `/admin/ollama/models/${l ? "unload" : "load"}`, { model: m.name })}>
                    {busy === "Load" || busy === "Unload" ? "Working…" : l ? "Unload" : "Load"}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <form onSubmit={save} className="rounded-lg border border-line bg-panel p-4">
        <h2 className="font-medium">Settings</h2>
        <p className="mt-1 text-sm text-muted">Model and context length apply to the next chat message. The rest apply when Ollama is started or restarted.</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="text-sm font-medium">Model used for chat
            <input className={input} list="installed" value={draft.active_model} onChange={(e) => set("active_model", e.target.value)} />
            <datalist id="installed">{status.installed.map((m) => <option key={m.name} value={m.name} />)}</datalist>
          </label>
          <label className="text-sm font-medium">Context length (tokens)
            <input className={input} type="number" min={512} max={262144} step={512} value={draft.context_length} onChange={(e) => set("context_length", Number(e.target.value))} />
          </label>
          <label className="text-sm font-medium sm:col-span-2">Models folder (OLLAMA_MODELS, empty = default)
            <input className={input} value={draft.models_dir} placeholder="/data/ollama/models" onChange={(e) => set("models_dir", e.target.value)} />
          </label>
          <label className="text-sm font-medium">Host (local only)
            <input className={input} value={draft.host} onChange={(e) => set("host", e.target.value)} />
          </label>
          <label className="text-sm font-medium">Keep model loaded
            <input className={input} value={draft.keep_alive} placeholder="5m" onChange={(e) => set("keep_alive", e.target.value)} />
          </label>
          <label className="text-sm font-medium">Parallel requests
            <input className={input} type="number" min={1} max={8} value={draft.num_parallel} onChange={(e) => set("num_parallel", Number(e.target.value))} />
          </label>
          <label className="text-sm font-medium">Max models in memory
            <input className={input} type="number" min={1} max={4} value={draft.max_loaded_models} onChange={(e) => set("max_loaded_models", Number(e.target.value))} />
          </label>
          <label className="flex items-center gap-2 text-sm font-medium sm:col-span-2">
            <input type="checkbox" checked={draft.flash_attention} onChange={(e) => set("flash_attention", e.target.checked)} />
            Flash attention
          </label>
        </div>
        <button disabled={!!busy} className="mt-4 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-60">
          {busy === "Save" ? "Saving…" : "Save settings"}
        </button>
      </form>

      <section className="rounded-lg border border-line bg-panel p-4">
        <button className="text-sm font-medium" onClick={() => setShowLogs((v) => !v)}>{showLogs ? "Hide log" : "Show log"}</button>
        {showLogs && <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-paper p-3 text-xs">{logs || "No log yet."}</pre>}
      </section>
    </main>
  );
}
