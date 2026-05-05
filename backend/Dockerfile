FROM python:3.13-slim

WORKDIR /app

# System deps for asyncpg, bcrypt, python-docx, pypdf
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency manifest first for layer caching
COPY pyproject.toml /app/pyproject.toml

# Install production deps only (no dev group)
RUN uv pip install --system --no-cache \
    $(python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(' '.join(d['project']['dependencies']))")

# Copy application code
COPY backend/ /app/backend/

# Runtime directories (CV uploads, logs, feeds, pages)
RUN mkdir -p /app/backend/cv_uploads /app/backend/logs \
             /app/backend/indeed_feeds /app/backend/job_pages

ENV PYTHONPATH=/app/backend
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "info"]