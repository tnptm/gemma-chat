"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { request } from "@/lib/api";

type ManagedUser = {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
  date_joined: string;
};
type UserForm = { username: string; email: string; password: string; is_admin: boolean };

const emptyForm: UserForm = { username: "", email: "", password: "", is_admin: false };

function errorMessage(value: unknown): string {
  const body = (value ?? {}) as Record<string, unknown>;
  if (typeof body.detail === "string") return body.detail;
  return Object.entries(body)
    .map(([key, message]) => `${key}: ${Array.isArray(message) ? message.join(" ") : String(message)}`)
    .join("; ") || "The request failed.";
}

export default function UserManagementPage() {
  const router = useRouter();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [form, setForm] = useState<UserForm>(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadUsers = useCallback(async () => {
    const response = await request("/admin/users/");
    if (response.status === 401) {
      router.replace("/login");
      return;
    }
    if (response.status === 403) {
      router.replace("/");
      return;
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(errorMessage(body));
      return;
    }
    setUsers(await response.json());
    setError("");
  }, [router]);

  useEffect(() => {
    let active = true;
    (async () => {
      const me = await request("/auth/me");
      if (!active) return;
      if (me.status === 401) {
        router.replace("/login");
        return;
      }
      if (!me.ok || !(await me.json()).is_admin) {
        router.replace("/");
        return;
      }
      await loadUsers();
      if (active) setLoading(false);
    })();
    return () => { active = false; };
  }, [loadUsers, router]);

  function startEdit(user: ManagedUser) {
    setEditingId(user.id);
    setForm({ username: user.username, email: user.email, password: "", is_admin: user.is_admin });
    setError("");
    setNotice("");
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(emptyForm);
    setError("");
  }

  async function saveUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    const payload: Record<string, unknown> = {
      username: form.username,
      email: form.email,
      is_admin: form.is_admin,
    };
    if (form.password) payload.password = form.password;
    const response = await request(
      editingId === null ? "/admin/users/" : `/admin/users/${editingId}`,
      {
        method: editingId === null ? "POST" : "PATCH",
        body: JSON.stringify(payload),
      },
    );
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      setError(errorMessage(body));
      setBusy(false);
      return;
    }
    cancelEdit();
    setNotice(editingId === null ? "User added." : "User updated.");
    await loadUsers();
    setBusy(false);
  }

  async function deleteUser(user: ManagedUser) {
    if (!window.confirm(`Delete user "${user.username}" and their conversations? This cannot be undone.`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    const response = await request(`/admin/users/${user.id}`, { method: "DELETE" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setError(errorMessage(body));
      setBusy(false);
      return;
    }
    if (editingId === user.id) cancelEdit();
    setNotice(`User "${user.username}" deleted.`);
    await loadUsers();
    setBusy(false);
  }

  const input = "mt-1 w-full rounded-md border border-line bg-white px-3 py-2 text-base outline-none focus:border-accent";
  const button = "rounded-md border border-line bg-white px-3 py-2 text-sm font-medium disabled:opacity-50";

  if (loading) return <main className="p-6 text-muted">Loading users…</main>;

  return (
    <main className="mx-auto max-w-3xl space-y-5 p-4 md:p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">User management</h1>
        <nav className="flex gap-4 text-sm">
          <Link href="/admin" className="text-accent hover:underline">Ollama dashboard</Link>
          <Link href="/" className="text-accent hover:underline">Back to chat</Link>
        </nav>
      </header>

      {(error || notice) && (
        <p role={error ? "alert" : "status"} className={`rounded-md border px-3 py-2 text-sm ${error ? "border-red-300 bg-red-50 text-red-800" : "border-line bg-panel"}`}>
          {error || notice}
        </p>
      )}

      <section className="rounded-lg border border-line bg-panel p-4">
        <h2 className="font-medium">Users</h2>
        {users.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No users found.</p>
        ) : (
          <ul className="mt-2 divide-y divide-line">
            {users.map((user) => (
              <li key={user.id} className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{user.username}</p>
                  <p className="text-sm text-muted">
                    {user.email || "No email"}
                    {" · "}
                    {user.is_admin ? "Administrator" : "Standard user"}
                    {" · Joined "}
                    {new Date(user.date_joined).toLocaleDateString()}
                  </p>
                </div>
                <button className={button} disabled={busy} onClick={() => startEdit(user)}>Edit</button>
                <button
                  className={`${button} text-red-700`}
                  disabled={busy}
                  onClick={() => deleteUser(user)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <form onSubmit={saveUser} className="space-y-4 rounded-lg border border-line bg-panel p-4">
        <h2 className="font-medium">{editingId === null ? "Add user" : "Edit user"}</h2>
        <label className="block text-sm font-medium">
          Username
          <input
            className={input}
            autoComplete="username"
            maxLength={150}
            required
            value={form.username}
            onChange={(event) => setForm({ ...form, username: event.target.value })}
          />
        </label>
        <label className="block text-sm font-medium">
          Email
          <input
            className={input}
            type="email"
            autoComplete="email"
            maxLength={254}
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
          />
        </label>
        <label className="block text-sm font-medium">
          {editingId === null ? "Password" : "New password (leave blank to keep current password)"}
          <input
            className={input}
            type="password"
            autoComplete="new-password"
            minLength={12}
            required={editingId === null}
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
          />
          <span className="mt-1 block font-normal text-muted">At least 12 characters.</span>
        </label>
        <label className="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={form.is_admin}
            onChange={(event) => setForm({ ...form, is_admin: event.target.checked })}
          />
          Administrator access
        </label>
        <div className="flex gap-2">
          <button className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={busy}>
            {busy ? "Saving…" : editingId === null ? "Add user" : "Save changes"}
          </button>
          {editingId !== null && (
            <button type="button" className={button} disabled={busy} onClick={cancelEdit}>Cancel</button>
          )}
        </div>
      </form>
    </main>
  );
}
