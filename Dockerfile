# Delivery analytics web app, for Azure App Service (Linux, custom container).
# Build:  docker build -t delivery-analytics:latest .
# Run:    docker run -p 8000:8000 -e PUBLIC_HOSTS=delivery.movedocs.com -v da-data:/home/data delivery-analytics:latest
FROM python:3.13-slim

# git: the "code" command clones Bitbucket repositories.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first so code changes reuse this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY delivery_analysis ./delivery_analysis
COPY github_analysis ./github_analysis
RUN uv sync --frozen --no-dev

# The SQLite database lives in /home/data. On App Service, /home is persistent storage
# (WEBSITES_ENABLE_APP_SERVICE_STORAGE=true), mounted over the network at start-up:
# - journal mode DELETE, because SQLite's WAL mode is unsafe on network file systems;
# - runs as root, because ownership set at build time does not apply to the mount;
# - run ONE instance only: SQLite cannot be shared across scaled-out instances.
ENV GITHUB_ANALYSIS_RESULTS=/home/data \
    SQLITE_JOURNAL_MODE=DELETE \
    BIND_HOST=0.0.0.0 \
    PORT=8000
# Secrets (ATLASSIAN, BITBUCKET, ANTHROPIC, ...) and PUBLIC_HOSTS come from App Service app settings.

EXPOSE 8000
CMD ["sh", "-c", "exec delivery-analysis serve --no-browser --port ${PORT}"]
