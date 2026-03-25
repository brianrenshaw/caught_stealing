FROM python:3.11-slim

# Install timezone data (needed by APScheduler for US/Eastern)
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (production only)
RUN uv sync --no-dev --no-install-project

# Copy application code
COPY app/ app/

EXPOSE 8080

# Use the venv directly (avoids uv run reinstalling dev deps at startup)
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
