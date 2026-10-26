# CLAUDE.md

Repository-wide rules (structure, security, verification) live in AGENTS.md and apply here too:

@AGENTS.md

Directory-specific notes: `backend/CLAUDE.md` and `frontend/CLAUDE.md`.

## What this is

Gemma Chat: a private, local-first chat app. Browser → Next.js (`frontend/`, port 3000)
→ rewrites `/api/*` → Django REST API (`backend/`, `127.0.0.1:8000`) → local Ollama
(`127.0.0.1:11434`). With `WEB_SEARCH_ENABLED=1`, the model can call a `web_search`
tool backed by SearXNG (compose service, `127.0.0.1:8888`). SQLite stores users and conversations. There is no public signup;
users are created by `createsuperuser` or by an admin in the UI.

## Commands

Python is managed **only with uv** (root `pyproject.toml` + `uv.lock`, `package = false`,
Python 3.15 from `.python-version`, venv in the root `.venv`). There is no
`requirements.txt`; don't add one or use pip.

```sh
uv sync                                   # from repo root: install locked deps
uv add <pkg>                              # add a backend dependency (updates uv.lock)

cd backend
uv run python manage.py check
uv run python manage.py test              # all Django tests
uv run python manage.py test accounts.tests.UserManagementTests.test_admin_can_delete_another_user
uv run python manage.py makemigrations && uv run python manage.py migrate
uv run python manage.py runserver 127.0.0.1:8000

cd ..                                     # Ollama control agent (host only, not in Docker)
uv run python ollama-agent/ollama_agent.py
uv run python -m unittest discover -s ollama-agent

cd frontend
npm install
npm run dev                               # http://localhost:3000
npm run build                             # type-check + production build (no lint/test scripts)

docker compose up -d --build              # from repo root: containerised backend + frontend
```

**Docker:** `compose.yaml` runs `backend/Dockerfile` (built from the repo root so it gets
`uv.lock`; runs migrate, then gunicorn on 127.0.0.1:8000) and `frontend/Dockerfile`
(`next start` on :3000). Both use `network_mode: host` and talk to the **host** Ollama.
The database is `./data/db.sqlite3`, bind-mounted at `/app/data` (`SQLITE_PATH`).
Local `runserver` still uses `backend/db.sqlite3`. The base images are pinned to the
local Python/Node/npm versions; when you upgrade locally, update the pins too.
`BACKEND_URL` is a frontend **build** argument because Next resolves rewrites at build time.

**Ollama control agent** (`ollama-agent/ollama_agent.py`): the only component that spawns
or kills `ollama serve`. It uses only the standard library plus psutil and python-dotenv,
and has its own `.env` (`OLLAMA_AGENT_API_KEY` ≥ 32 chars, `OLLAMA_AGENT_BIND` loopback-only,
`OLLAMA_BIN`). The API is `GET /status`, `POST /start|/restart|/stop`, `GET /logs`, all with a
Bearer key. State and logs are in `ollama-agent/run/`. It validates every setting itself
because other programs may call it, and it strips `OLLAMA_*`/`DJANGO_*`/... from the child
env so the key never reaches Ollama. It never kills a process it didn't start (pid + create
time). Keep it loopback-only. Exposing it beyond that needs an explicit request and a security review.

## Cross-cutting conventions

- **API URLs have no trailing slash** (`APPEND_SLASH = False`, `SimpleRouter(trailing_slash=False)`),
  e.g. `/api/conversations/<uuid>/chat`. The exception is the user-management list,
  `/api/admin/users/`, which is mounted with a trailing slash.
- **Auth contract:** JWTs in httpOnly cookies, plus a `csrftoken` cookie that the frontend
  echoes back in `X-CSRFToken` on every non-GET request. `frontend/lib/api.ts` handles this
  and retries once through `/api/auth/refresh` after a 401. Any new endpoint works with
  this flow automatically, as long as the frontend calls it through `request()`/`api()`.
- **Admin** means `user.is_staff`. The API exposes it as `is_admin` (`/api/auth/me` and the
  user-management serializer). The backend enforces it with `accounts.permissions.IsAppAdmin`.
  Frontend admin checks only decide where to redirect.
- **Errors:** DRF validation errors come back as `{field: [msgs]}` or `{detail: "..."}`.
  The admin pages turn these into text with a local `errText`/`errorMessage` helper.
- When an API shape changes, update the matching TypeScript types (in `lib/api.ts` or
  inline in the page) in the same change.

## Never commit

`backend/.env`, `backend/db.sqlite3`, `data/` (except `.gitkeep`), `backend/run/`, `ollama-agent/.env`, `ollama-agent/run/`, `.venv/`,
`node_modules/`, `.next/`, and the `*.zip` archives in the repo root.
