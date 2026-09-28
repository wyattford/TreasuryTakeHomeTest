FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app

# The database and uploaded images live on volumes (see docker-compose.yml).
RUN mkdir -p /app/data /app/uploads
ENV PATH="/app/.venv/bin:$PATH" DATABASE_URL=sqlite:////app/data/ttb_review.db

EXPOSE 8000
# One worker: background extractions and batch runners live in this process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
