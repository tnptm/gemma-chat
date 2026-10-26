# Build context: repository root (needs pyproject.toml + uv.lock from there).
FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.15.0-slim-trixie

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

# Exact versions from uv.lock
WORKDIR /src
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project

# Same uid/gid as the host user so the bind-mounted ./data stays writable
ARG UID=1000
ARG GID=1000
RUN groupadd -g "$GID" app && useradd -u "$UID" -g app -m -s /usr/sbin/nologin app

WORKDIR /app
COPY --chown=app:app backend/ ./
RUN mkdir -p /app/data /app/run && chown app:app /app/data /app/run

USER app
ENV SQLITE_PATH=/app/data/db.sqlite3
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi -k gthread --threads 8 -b ${BIND:-127.0.0.1:8000} --timeout 300"]
