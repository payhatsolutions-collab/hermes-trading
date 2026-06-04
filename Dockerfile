FROM python:3.11-slim
WORKDIR /app

# Install curl + ca-certificates (needed for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Copy project files
COPY pyproject.toml ./
COPY hermes_trading/ ./hermes_trading/
COPY state/ ./state/

# Sync dependencies (creates venv, installs all packages)
RUN uv sync

# Runtime mode: paper (default) or live — controlled by .env
ENV HERMES_TRADING_MODE=paper
ENV PYTHONUNBUFFERED=1

# Use the sync'd venv python
CMD ["uv", "run", "python", "hermes_trading/run.py"]