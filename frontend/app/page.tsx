"use client";

import { KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, request, type Conversation, type ConversationDetail, type Message } from "@/lib/api";
import MarkdownRenderer from "@/components/MarkdownRenderer";

export default function Home() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [menu, setMenu] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);


  // State to hold user info
  const [userName, setUserName] = useState<string>("User");
  const [isAdmin, setIsAdmin] = useState(false);

  const loadConvs = useCallback(async () => setConvs(await api<Conversation[]>("/conversations")), []);

  useEffect(() => {
    (async () => {
      const me = await request("/auth/me");
      if (!me.ok) return router.replace("/login");

      // Read the JSON body from the response
      const userData = await me.json();

      if (userData && userData.username) {
        setUserName(userData.username);
        setIsAdmin(userData.is_admin === true);
      } else {
        setUserName("Guest");
      }

      await loadConvs();
      setReady(true);
    })();
  }, [router, loadConvs]);

  useEffect(() => bottom.current?.scrollIntoView({ block: "end" }), [messages]);

  async function openConv(id: string) {
    abort.current?.abort();
    setActiveId(id);
    setMenu(false);
    setError("");
    const c = await api<ConversationDetail>(`/conversations/${id}`);
    setMessages(c.messages);
  }

  function newChat() {
    abort.current?.abort();
    setActiveId(null);
    setMessages([]);
    setError("");
    setMenu(false);
  }

  async function removeConv(id: string) {
    if (!confirm("Delete this conversation?")) return;
    await api(`/conversations/${id}`, { method: "DELETE" });
    if (id === activeId) newChat();
    loadConvs();
  }

  async function logout() {
    await request("/auth/logout", { method: "POST" });
    router.replace("/login");
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError("");
    setBusy(true);
    const ctrl = new AbortController();
    abort.current = ctrl;
    const aid = `a${Date.now()}`;
    try {
      let id = activeId;
      if (!id) {
        const c = await api<Conversation>("/conversations", { method: "POST", body: "{}" });
        id = c.id;
        setActiveId(id);
      }
      setMessages((m) => [...m, { id: `u${Date.now()}`, role: "user", content: text }, { id: aid, role: "assistant", content: "" }]);
      const res = await request(`/conversations/${id}/chat`, {
        method: "POST",
        body: JSON.stringify({ content: text }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) throw new Error(res.status === 429 ? "Slow down a little, then try again." : "The request failed.");
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = dec.decode(value, { stream: true });
        setMessages((m) => m.map((x) => (x.id === aid ? { ...x, content: x.content + chunk } : x)));
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message || "Something went wrong.");
    } finally {
      setBusy(false);
      abort.current = null;
      loadConvs();
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  }

  if (!ready) return <main className="p-6 text-muted">Loading…</main>;

  return (
    <div className="flex h-dvh">
      {menu && <div className="fixed inset-0 z-10 bg-ink/40 md:hidden" onClick={() => setMenu(false)} />}

      <aside className={`fixed inset-y-0 left-0 z-20 flex w-72 flex-col border-r border-line bg-panel transition-transform md:static md:translate-x-0 ${menu ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="p-3">
          <h2 className="text-2xl">Gemma4:e2b Chat</h2>

        </div>

        <div className="p-3">
          <button onClick={newChat} className="w-full rounded-md bg-accent px-3 py-2.5 text-sm font-medium text-white">
            New chat
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2" aria-label="Conversations">
          {convs.length === 0 && <p className="px-2 py-3 text-sm text-muted">No conversations yet. Type a message to start one.</p>}
          {convs.map((c) => (
            <div key={c.id} className={`group flex items-center rounded-md ${c.id === activeId ? "bg-accent-soft" : "hover:bg-paper"}`}>
              <button onClick={() => openConv(c.id)} className="min-w-0 flex-1 truncate px-2 py-2.5 text-left text-sm">
                {c.title}
              </button>
              <button onClick={() => removeConv(c.id)} aria-label={`Delete ${c.title}`}
                      className="px-2 py-2 text-muted hover:text-red-700 md:opacity-0 md:group-hover:opacity-100 md:focus:opacity-100">
                ✕
              </button>
            </div>
          ))}
        </nav>
        <div className="border-t border-line p-3">
          <p>Logged in: <span className="font-semibold" >{ userName }</span>
            <button onClick={logout} className="p-3 text-sm text-muted hover:text-ink underline"> Sign out</button></p>
          <div className="p-3">
            <ul>
              <li className="list-disc">{isAdmin && <Link href="/admin" className="text-sm text-accent hover:underline">Ollama dashboard</Link>}</li>
              <li className="list-disc">ToDO user admin</li>
            </ul>
          </div>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-line bg-panel px-3 py-2 md:hidden">
          <button onClick={() => setMenu(true)} aria-label="Open conversations" className="rounded-md px-2 py-1 text-xl">☰</button>
          <span className="truncate text-sm font-medium">{convs.find((c) => c.id === activeId)?.title ?? "New chat"}</span>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
            {messages.length === 0 && (
              <p className="pt-16 text-center text-muted">Ask anything. Everything stays on your machine.</p>
            )}
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="ml-auto w-fit max-w-[85%] whitespace-pre-wrap break-words rounded-lg bg-accent-soft px-4 py-2.5 border border-t-cyan-800">
                  {//<MarkdownRenderer markdown={m.content} />
                  }
                  { m.content}
                </div>
              ) : (
                  <div key={m.id} className="max-w-full whitespace-pre-wrap break-words leading-relaxed">

                    {
                      m.content.length > 0 ?
                      <MarkdownRenderer markdown={m.content} /> :
                      <span className="text-muted">Thinking…</span>
                    }
                  </div>
              ),
            )}
            {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
            <div ref={bottom} />
          </div>
        </div>

        <div className="border-t border-line bg-panel p-3">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKey}
                      rows={1} placeholder="Message" maxLength={8000} aria-label="Message"
                      className="field-sizing-content max-h-40 min-h-11 flex-1 resize-none rounded-md border border-line bg-white px-3 py-2.5 text-base outline-none focus:border-accent" />
            {busy ? (
              <button onClick={() => abort.current?.abort()} className="h-11 rounded-md border border-line px-4 text-sm font-medium">Stop</button>
            ) : (
              <button onClick={send} disabled={!input.trim()} className="h-11 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50">Send</button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
