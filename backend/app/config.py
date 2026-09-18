from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor path-like defaults to the backend package's location, not the
# launching process's cwd — uvicorn can be started from the repo root (e.g.
# `uv run --project backend uvicorn app.main:app --app-dir backend`), and a
# plain relative path would then land in the wrong directory.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, overridable via environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="", extra="ignore")

    # Ollama server used for label extraction. Points at the Mac during local
    # dev; re-point at the Linux/AMD GPU box later by changing this one value.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5vl"
    ollama_timeout_seconds: float = 30.0

    database_url: str = f"sqlite:///{BACKEND_DIR / 'ttb_review.db'}"

    # Comma-separated list of allowed frontend origins for CORS.
    cors_origins: str = "http://localhost:3000"

    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB, matches the reference impl's limit

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
