# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PORT=8788 \
    HOME=/home/app \
    KEEP_DATA_DIR=/home/app/.keep-mcp

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN uv sync --frozen --no-dev \
    && useradd --create-home --home-dir /home/app --shell /bin/bash app \
    && mkdir -p /home/app/.keep-mcp \
    && chown -R app:app /home/app /app

USER app
EXPOSE 8788

CMD ["uv", "run", "--no-sync", "keep-mcp-http"]
