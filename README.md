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
- Admin-only Ollama management dashboard for starting/stopping the local model runtime, checking installed models, loading/unloading models, and adjusting runtime configuration such as context length, concurrency, and keep-alive behavior.
- Local-only deployment posture: the API is kept on loopback, the frontend uses app-side proxying, and access control is designed for private or trusted network use rather than open public access.
- Built-in rate limiting and server-side protections around authentication and chat requests to help reduce abuse and accidental overuse.

In short, the application gives you a private, controlled chat workspace with model administration and secure local deployment, while keeping the architecture simple enough to run on a single machine.

## 1. Model
    ollama list            # confirm the exact tag, e.g. gemma4
    # if the tag differs, set OLLAMA_MODEL in backend/.env

## 2. Backend
    cd backend
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env     # set DJANGO_SECRET_KEY (see comment inside)
    python manage.py migrate
    python manage.py createsuperuser   # the only way to add a user: no public signup
    python manage.py runserver 127.0.0.1:8000

## 3. Frontend
    cd frontend
    npm install
    npm run dev              # http://localhost:3000

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
- Run Django with: gunicorn config.wsgi -k gthread --threads 8 -b 127.0.0.1:8000 --timeout 300
  and the frontend with: npm run build && npm start
