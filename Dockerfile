FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.9.22 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_COMPILE_BYTECODE=1 \
    STORAGE_ROOT=/data \
    PORT=8000 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend ./backend
RUN uv sync --locked --no-dev --no-editable \
    && mkdir -p /data

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn editmaxxing.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
