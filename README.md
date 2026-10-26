# Gemma chat (Django + Next.js)

Gemma Chat is a private, local-first chat application built around a locally hosted Gemma model via Ollama. It combines a Django REST API, a Next.js chat interface, and a lightweight SQLite database to give you an end-to-end, self-hosted AI workspace without exposing your conversations or model settings to the public internet.

## Project overview

This project is designed to feel like a small, secure internal AI assistant app. It is centered around these features:

- Local model inference through Ollama with a configurable model, context length, and runtime settings.
- Per-user chat conversations stored in SQLite, with each message tied to the authenticated user and a conversation title auto-generated from the first prompt.
- Streaming chat responses from the backend so the model output appears progressively in the browser instead of waiting for a full response.
- Markdown rendering in the frontend, so assistant responses can include structured formatting, lists, headings, and code blocks in a readable layout.
- Secure login and session handling using JWTs in secure, httpOnly cookies with CSRF protection and refresh-token rotation.
- No public registration flow: the app is intended for a controlled environment where an admin creates accounts, and each API request is filtered by the currently logged-in user.
- Admin-only user management for listing, creating, editing, and deleting accounts, including assigning administrator access.
- Admin-only Ollama management dashboard for starting/stopping the local model runtime, checking installed models, loading/unloading models, and adjusting runtime configuration such as context length, concurrency, and keep-alive behavior.
- Local-only deployment posture: the API is kept on loopback, the frontend uses app-side proxying, and access control is designed for private or trusted network use rather than open public access.
- Built-in rate limiting and server-side protections around authentication and chat requests to help reduce abuse and accidental overuse.

In short, the application gives you a private, controlled chat workspace with model administration and secure local deployment, while keeping the architecture simple enough to run on a single machine.

## 1. Model
Pull models with the `ollama` CLI. This needs a running Ollama, either one started
from the dashboard through the agent (section 3) or a temporary `ollama serve`.

    ollama list            # confirm the exact tag, e.g. gemma4
    # if the tag differs, set OLLAMA_MODEL in backend/.env

## 2. Backend
Python dependencies are managed with [uv](https://docs.astral.sh/uv/) via the
root `pyproject.toml` and `uv.lock` (add packages with `uv add <package>`).

    uv sync                  # creates .venv in the repo root and installs locked deps
    cd backend
    cp .env.example .env     # set DJANGO_SECRET_KEY (see comment inside)
    uv run python manage.py migrate
    uv run python manage.py createsuperuser   # the only way to add a user: no public signup
    uv run python manage.py runserver 127.0.0.1:8000

## 3. Ollama control agent
The dashboard's Start, Stop and Restart buttons go through `ollama-agent/`, a small
Python service that runs on the host. It owns the `ollama serve` process and starts
it with the dashboard's settings. It listens on 127.0.0.1:11435 only, and every
request needs an API key, so scripts and the command line can use it as well.

    cp ollama-agent/.env.example ollama-agent/.env
    # Set OLLAMA_AGENT_API_KEY in ollama-agent/.env and in backend/.env (same value):
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    uv run python ollama-agent/ollama_agent.py          # keep running (separate terminal)

API (`Authorization: Bearer <key>`, JSON):

| Method | Path | Body / query |
|---|---|---|
| GET | `/status` | |
| POST | `/start`, `/restart` | optional settings: `host` (loopback:port), `context_length`, `keep_alive`, `num_parallel`, `max_loaded_models`, `flash_attention`, `models_dir` |
| POST | `/stop` | |
| GET | `/logs` | `?lines=200` (max 1000) |

    KEY=...   # the API key
    curl -H "Authorization: Bearer $KEY" http://127.0.0.1:11435/status
    curl -H "Authorization: Bearer $KEY" -X POST -d '{"context_length": 16384}' http://127.0.0.1:11435/restart

The agent can only stop an Ollama it started itself. If an Ollama systemd service
holds port 11434, start fails. To manage Ollama only through the agent, disable the
service with `sudo systemctl disable --now ollama.service`.

## 4. Frontend
    cd frontend
    npm install
    npm run dev              # http://localhost:3000

## Alternative: Docker Compose (Linux)
Runs Django (gunicorn) and Next.js (`next start`) in containers; Ollama keeps running
on the host. Both containers use host networking, so Django stays on 127.0.0.1:8000
and reaches Ollama at 127.0.0.1:11434. Images use the same versions as local
development: Python 3.15.0 with packages from `uv.lock`, and Node 24.22.1 / npm 12.2.1
with packages from `package-lock.json`.

    cp backend/.env.example backend/.env   # if not done yet; read via env_file
    docker compose up -d --build            # http://localhost:3000
    docker compose exec backend python manage.py createsuperuser

- The SQLite database lives in `data/db.sqlite3` on the host and is mounted into
  the backend container at `/app/data`. It is never copied into an image, and
  migrations run on every container start. To start with an existing local
  database, copy `backend/db.sqlite3` to `data/db.sqlite3`.
- The containers run as uid/gid 1000. If your host user differs, build with
  `UID=$(id -u) GID=$(id -g) docker compose build`.
- Run the Ollama control agent on the host (section 3) so the dashboard can start
  and stop Ollama. The backend container reaches it at 127.0.0.1:11435.
- `next dev` and the frontend container both use port 3000, so stop one before
  starting the other.

## Security design
- JWTs only in httpOnly, SameSite=Strict cookies (never in localStorage / JS).
- Access token 10 min; refresh token 7 days, rotated on every use, old one blacklisted; logout revokes server-side.
- Refresh cookie is scoped to /api/auth/ so it is not sent with ordinary API calls.
- CSRF token (double submit) required on every state-changing request, login included.
- Argon2 password hashing, 12+ char password validators, login throttled to 5/min, chat to 30/min.
- No registration endpoint; every query is filtered by the logged-in user.
- Next.js proxies /api/* to Django, so Django can stay bound to 127.0.0.1.
- Messages are rendered as plain text (no HTML injection).

## Going beyond localhost
- Serve over HTTPS (Caddy, or Tailscale/`tailscale serve`), then set in backend/.env:
  DJANGO_DEBUG=0, COOKIE_SECURE=1, DJANGO_ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS to your real host/origin.
- Run Django (from backend/) with: uv run gunicorn config.wsgi -k gthread --threads 8 -b 127.0.0.1:8000 --timeout 300
  and the frontend with: npm run build && npm start
