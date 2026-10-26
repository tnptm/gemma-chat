# AI development guidance

These instructions apply to the entire repository.

## Project structure

- `backend/` contains the Django REST API. Apps include `accounts/` for
  authentication, `chat/` for conversations and Ollama chat, and `control/`
  for the admin Ollama dashboard.
- `ollama-agent/` is a standalone, small Python service that runs on the
  host. It starts and stops `ollama serve`, and its API is loopback-only and
  protected by an API key. Django's `control` app calls it, as can other programs.
- `searxng/` holds the settings for the local SearXNG search service used by the
  chat's optional `web_search` tool (`backend/chat/websearch.py`).
- `frontend/` contains the Next.js and React UI. Shared API helpers are in
  `frontend/lib/`, and reusable UI components are in `frontend/components/`.
- The application is local-first: Ollama serves the model, Django stores
  conversations in SQLite, and Next.js proxies `/api/*` requests to Django.

## Before changing code

- Read the relevant implementation and nearby code before editing; follow
  existing naming, formatting, and framework patterns.
- Check `git status` first. Preserve pre-existing user changes and do not
  overwrite or remove unrelated files.
- Make focused changes that address the request without unrelated refactoring.
- Update directly related documentation when behavior, setup, or configuration
  changes.

## Security and data handling

- Keep every conversation query scoped to the authenticated user.
- Preserve the existing cookie-based JWT, CSRF, throttling, and permission
  protections. Do not move authentication tokens into browser storage.
- Validate inputs at the backend boundary and avoid exposing secrets or
  sensitive details in errors.
- Never read, copy into output, or commit credentials or private runtime data.
  In particular, do not add `.env` files, SQLite databases, logs, or generated
  runtime artifacts to source control.
- Do not introduce public registration or expose the local Ollama service to
  untrusted networks without an explicit request and security review.

## Changes and verification

- Backend changes should follow the Django/DRF patterns in the relevant app.
  When practical, run `cd backend && python manage.py check`; run relevant tests
  if they exist.
- Frontend changes should follow the existing TypeScript and React patterns.
  Run `cd frontend && npm run build` when dependencies are available.
- For changes that affect both frontend and backend, check that the API
  contract and user-visible behavior remain consistent.
- Report checks that were run and any relevant limitations. Do not claim a
  check passed unless it completed successfully.
