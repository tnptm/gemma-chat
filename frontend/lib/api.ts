export type Conversation = { id: string; title: string; created_at: string; updated_at: string };
export type Message = { id: string | number; role: "user" | "assistant"; content: string };
export type ConversationDetail = Conversation & { messages: Message[] };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const getCsrf = () =>
  document.cookie.split("; ").find((c) => c.startsWith("csrftoken="))?.split("=")[1] ?? "";

async function ensureCsrf() {
  if (!getCsrf()) await fetch("/api/auth/csrf", { credentials: "same-origin" });
}

// Never retry these through the refresh flow
const NO_REFRESH = new Set(["/auth/login", "/auth/refresh", "/auth/logout"]);
let refreshing: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    await ensureCsrf();
    const r = await fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": getCsrf() },
    });
    return r.ok;
  })().finally(() => (refreshing = null));
  return refreshing;
}

/** fetch wrapper: cookies + CSRF header + one transparent refresh on 401. */
export async function request(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET") {
    await ensureCsrf();
    headers.set("X-CSRFToken", getCsrf());
  }
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  const res = await fetch(`/api${path}`, { ...init, headers, credentials: "same-origin" });
  if (res.status === 401 && retry && !NO_REFRESH.has(path) && (await refreshSession())) {
    return request(path, init, false);
  }
  return res;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await request(path, init);
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return (res.status === 204 ? undefined : await res.json()) as T;
}
