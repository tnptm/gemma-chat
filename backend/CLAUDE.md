# Backend (Django + DRF)

Run everything from `backend/` with `uv run` (see root CLAUDE.md for the command list).
Settings are in `config/settings.py` and read `backend/.env` via python-dotenv. Use
`.env.example` as the template, and add any new setting there with a comment.
The database path comes from `SQLITE_PATH` (default `backend/db.sqlite3`; Docker uses
`/app/data/db.sqlite3`).

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
- `ollama.stream_chat()` is a tool loop that yields events: `("text", chunk)`,
  `("search", query)` and `("sources", [(title, url)])`. The view streams a progress line
  for each search, but saves only the answer text plus the **Sources** block. The
  system prompt comes from `ollama.system_prompt()` and includes today's date.
- **Web search** (`chat/websearch.py`, enabled by `WEB_SEARCH_ENABLED`): SearXNG JSON API
  at `SEARXNG_URL`, then it fetches the top pages and keeps the passages that match the
  query (`relevant_excerpt`). Output is capped by `RESULT_CHARS` so a small context window
  doesn't overflow. Limits: `MAX_TOOL_ROUNDS`/`MAX_CALLS_PER_ROUND` in `ollama.py`.
- Page fetching must go through `_page_client()`. Its httpcore backend refuses
  non-public IPs at connect time (SSRF/DNS-rebinding protection). It replaces the
  private `HTTPTransport._pool`, and `chat/tests.py` checks that this still works after
  httpx upgrades. Any model- or web-derived text placed into the Markdown answer must
  go through `markdown_text()`/`format_sources()`.
- Chat uses `settings.OLLAMA_URL` and `settings.OLLAMA_MODEL` from `.env`. It does
  **not** use the dashboard's `OllamaConfig.host`/`active_model`. Keep that in mind
  if you change which model chat uses.

## Ollama control (`control/`)

- `OllamaConfig` is a single-row model (always `pk=1`, use `OllamaConfig.load()`).
  Field validators restrict `host` to loopback-only, and also validate model names,
  `keep_alive` and absolute `models_dir`. Keep those validators.
- Django does **not** spawn processes. Start, stop, restart and logs go to the host-side
  control agent (`ollama-agent/`) through `services._agent()`, using `OLLAMA_AGENT_URL` and
  `Authorization: Bearer OLLAMA_AGENT_API_KEY`. `cfg.server_settings()` is the request body.
  The agent re-validates it, so keep both sides' validation in sync when adding a setting.
- Status, the model list and load/unload still call Ollama's HTTP API directly at
  `cfg.host`. `status()` merges in the agent's `managed`/`pid`/`binary_found` plus
  `agent_ok`/`agent_error`, and the dashboard UI reads those fields.
- Views subclass `AdminView`. Use `self.run(fn, ...)` so that `ServiceError` becomes a
  409 `{detail}` and the response returns the full status.
- `control/tests.py` mocks `httpx.request` (agent) and `services._get` (Ollama).

## Tests

Tests are in `accounts/tests.py`, `chat/tests.py` and `control/tests.py` (`APITestCase`, `force_authenticate`). Add tests
for new behaviour in the app's `tests.py`. Tests must not require a running Ollama, SearXNG or internet access.
