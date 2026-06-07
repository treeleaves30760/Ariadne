# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

# uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# curl + ca-certificates to fetch the Codex CLI
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install the pinned, standalone (static musl) Codex CLI for the target arch.
ARG CODEX_VERSION=0.136.0
ARG TARGETARCH
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) triple=x86_64-unknown-linux-musl ;; \
      arm64) triple=aarch64-unknown-linux-musl ;; \
      *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${triple}.tar.gz"; \
    curl -fsSL "$url" -o /tmp/codex.tar.gz; \
    tar -xzf /tmp/codex.tar.gz -C /tmp; \
    mv "/tmp/codex-${triple}" /usr/local/bin/codex; \
    chmod +x /usr/local/bin/codex; \
    rm /tmp/codex.tar.gz; \
    codex --version

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install dependencies first (cached unless the lockfile changes). package=false -> deps only.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app

# Non-root user with a real home for ~/.codex; pre-create the volume mount points so the
# named volumes inherit correct ownership on first mount.
RUN useradd -m -u 10001 app \
    && mkdir -p /home/app/.codex /data \
    && chown -R app:app /home/app /data
USER app
ENV HOME=/home/app PATH="/app/.venv/bin:$PATH"

EXPOSE 8008
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008"]
