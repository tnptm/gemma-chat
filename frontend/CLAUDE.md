# Frontend (Next.js 16 App Router, React 19, Tailwind 4, TypeScript strict)

Commands: `npm run dev`, `npm run build`. The build is the only check; there are no lint
or test scripts. The `@/*` import alias maps to the `frontend/` root.

## Layout

- `app/page.tsx`: the main chat UI (conversation sidebar, streaming messages, admin links).
- `app/login/page.tsx`: the sign-in form.
- `app/admin/page.tsx`: the Ollama dashboard. It polls `/admin/ollama/status` every 5 s and logs every 3 s.
- `app/admin/users/page.tsx`: admin user management (list, create, edit, delete).
- `lib/api.ts`: the **only** way to call the backend (`request()`, `api<T>()`, shared types).
- `components/MarkdownRenderer.tsx`: `react-markdown` + `remark-gfm`, used for assistant messages.
- `next.config.mjs`: rewrites `/api/:path*` to `BACKEND_URL` (default `http://127.0.0.1:8000`),
  turns compression off so streamed chat isn't buffered, sets a 300 s proxy timeout, and
  adds security headers.

## Conventions

- Every page is a client component (`"use client"`). On mount, a page calls
  `request("/auth/me")`, redirects to `/login` on failure, and admin pages redirect
  non-admins to `/`. These redirects are only UX; the backend enforces access.
- Call the API through `request(path, init)` or `api<T>(path, init)`. Paths leave out the
  `/api` prefix. These helpers send `credentials: "same-origin"`, attach `X-CSRFToken` on
  non-GET requests, set the JSON content type when there is a body, and refresh the
  token after a 401. Don't call `fetch("/api/...")` directly, and never store tokens in
  `localStorage`/`sessionStorage` or JS-readable cookies.
- Chat responses are streamed plain text, read with `res.body.getReader()` and an
  `AbortController` (the Stop button). Don't switch to `api()` for that endpoint.
- Never render model output as raw HTML: no `dangerouslySetInnerHTML`, and no
  `rehype-raw` in the Markdown renderer. User messages are shown as plain text.
- Styling is Tailwind utility classes only. Theme colours are defined in `app/globals.css`
  under `@theme` (`paper`, `panel`, `ink`, `muted`, `line`, `accent`, `accent-soft`), so use
  e.g. `bg-panel text-muted border-line` rather than raw hex values.
- `MarkdownRenderer` uses `prose` classes, but `@tailwindcss/typography` is not installed,
  so they currently do nothing.
- Types for page-specific API responses are declared inline at the top of the page
  (e.g. `Config`, `Status`, `ManagedUser`). Shared chat types live in `lib/api.ts`.
