# syntax=docker/dockerfile:1

FROM python:3.13-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files first (for layer caching)
COPY pyproject.toml uv.lock README.md ./

# Install dependencies (no dev deps in production)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY src/ src/
COPY .env.example .env.example

# Install the project itself
RUN uv sync --frozen --no-dev

# Default command: run in service mode
CMD ["uv", "run", "python", "-m", "hkjc_scrapper.main"]
