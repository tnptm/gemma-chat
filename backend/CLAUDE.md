# Backend (Django + DRF)

Run everything from `backend/` with `uv run` (see root CLAUDE.md for the command list).
Settings are in `config/settings.py` and read `backend/.env` via python-dotenv. Use
`.env.example` as the template, and add any new setting there with a comment.

## Layout

| App | Mounted at | Purpose |
|---|---|---|
| `accounts/` | `/api/auth/` | `csrf`, `login`, `refresh`, `logout`, `me` (`views.py`) |
| `accounts/` | `/api/admin/users/` | admin user CRUD (`admin_views.py`, `admin_serializers.py`) |
| `chat/` | `/api/` | `ConversationViewSet` + streaming `POST conversations/<id>/chat` |
| `control/` | `/api/admin/ollama/` | start/stop/restart Ollama, load/unload models, config, logs |

There is no `django.contrib.admin`, sessions, or templates. The API is JSON-only:
it uses `JSONRenderer` and `JSONParser` only.

## Auth and security patterns (keep these intact)

- The default auth class is `accounts.authentication.CookieJWTAuthentication`. It reads
  the `access_token` cookie (path `/api/`) and calls `enforce_csrf()` for unsafe methods.
  The `refresh_token` cookie is scoped to `/api/auth/`.
- Public endpoints subclass `_Public` (no auth classes, `AllowAny`) and must call
  `enforce_csrf(request)` themselves in POST handlers.
- The default permission is `IsAuthenticated`. Admin endpoints set
  `permission_classes = [IsAppAdmin]` (`accounts/permissions.py`).
- Throttling uses `ScopedRateThrottle`, and the scopes are defined in `REST_FRAMEWORK`
  in settings: `login` 5/min, `chat` 30/min, `admin` 30/min. Set `throttle_scope` on new
  views. If a new scope is needed, add it to settings.
- Conversation queries must go through `get_queryset()`, which filters by
  `request.user`. Never look up a `Conversation` by id alone.
- Passwords are hashed with Argon2, and validators require at least 12 characters. When
  creating or updating users, call `set_password()` and run `password_validation`.
- Admin user management blocks self-deletion and self-demotion, and tests cover this.

## Chat flow (`chat/views.py`, `chat/ollama.py`)

- `chat` saves the user message, sets the title from the first 60 characters if it is
  still `"New chat"`, and builds the payload: the system prompt plus the last
  `CHAT_HISTORY_LIMIT` messages.
- The response is a `StreamingHttpResponse` of **plain text** chunks, not SSE/JSON.
  Ollama failures are added to the stream as `[Error: ...]` text. The assistant
  message is saved in `finally`, so a partial reply is kept when the client aborts.
- Chat uses `settings.OLLAMA_URL` and `settings.OLLAMA_MODEL` from `.env`. It does
  **not** use the dashboard's `OllamaConfig.host`/`active_model`. Keep that in mind
  if you change which model chat uses.

## Ollama control (`control/`)

- `OllamaConfig` is a single-row model (always `pk=1`, use `OllamaConfig.load()`).
  Field validators restrict `host` to loopback-only, and also validate model names,
  `keep_alive` and absolute `models_dir`. Keep those validators.
- `services.py` runs `ollama serve` with `subprocess.Popen` and a fixed env allowlist
  from `cfg.env()`. It strips `DJANGO_`/`CSRF_`/`COOKIE_`/`CHAT_`/`OLLAMA_` vars from the
  child env. The process is tracked in `run/ollama.pid` as `pid:create_time`, so a
  recycled PID is never killed. Logs go to `run/ollama.log`.
- Views subclass `AdminView`. Use `self.run(fn, ...)` so that `ServiceError` becomes a
  409 `{detail}` and the response returns the full status.

## Tests

The only tests are `accounts/tests.py` (`APITestCase`, `force_authenticate`). Add tests
for new behaviour in the app's `tests.py`. Tests must not require a running Ollama.
