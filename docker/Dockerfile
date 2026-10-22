FROM ghcr.io/astral-sh/uv:0.11.26 AS installer
FROM node:24-bookworm-slim
# Chromium and fonts are installed at build time so PDF printing never
# downloads a browser at run time.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates mariadb-client build-essential pkg-config libmariadb-dev libffi-dev chromium fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji && rm -rf /var/lib/apt/lists/*
COPY --from=installer /uv /uvx /usr/local/bin/
WORKDIR /app
COPY . .
RUN ./review/prepare-local
ENV PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin" FRAPPE_PRELOAD_DATABASE_DRIVERS=none
CMD ["./docker/serve"]
