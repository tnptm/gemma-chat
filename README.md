# Gemma chat (Django + Next.js)

Private chat UI for a local Gemma model served by Ollama. Conversations live in SQLite.

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
