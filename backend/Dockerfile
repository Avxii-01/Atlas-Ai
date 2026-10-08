FROM python:3.14-slim

# Install uv from official Astral image
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Configure uv for container environment
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install dependencies into container virtual environment using frozen lockfile
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Place virtual environment executables at front of PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy backend application source
COPY . /app

# Expose backend service port
EXPOSE 8000

# Run minimal FastAPI placeholder service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
