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
    # Per-request timeout for one extraction call. Generous because a cold
    # model load alone can take ~20s; requests queued behind our own
    # concurrency limit below don't count against it.
    ollama_timeout_seconds: float = 120.0
    # How long Ollama keeps the model resident after a request. Long enough
    # that ordinary gaps between reviews don't force a cold reload.
    ollama_keep_alive: str = "30m"
    # Extraction calls allowed in flight to Ollama at once. Anything beyond
    # this waits in-process (see app/extraction_service.py) instead of piling
    # up in Ollama's own queue and timing out there. Match this to the
    # server's OLLAMA_NUM_PARALLEL.
    ollama_max_concurrency: int = 2
    # Load the model into memory when the backend starts, so the first real
    # upload doesn't pay the cold-load cost.
    ollama_warmup_on_startup: bool = True

    # Uploaded label photos are re-encoded with their long edge capped at this
    # many pixels before extraction: the vision model's cost scales with image
    # size (1300px -> 1024px cut qwen2.5vl's input processing from ~8s to ~4.7s
    # per image on an M4 Pro), and phone photos are far larger than label text
    # needs.
    max_image_edge_px: int = 1024

    database_url: str = f"sqlite:///{BACKEND_DIR / 'ttb_review.db'}"

    # Comma-separated list of allowed frontend origins for CORS.
    cors_origins: str = "http://localhost:3000"

    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB per file

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
