from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor path-like defaults to the backend package's location, not the
# launching process's cwd — uvicorn can be started from the repo root (e.g.
# `uv run --project backend uvicorn app.main:app --app-dir backend`), and a
# plain relative path would then land in the wrong directory.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, overridable via environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="", extra="ignore")

    # Which service runs the vision model: "ollama" (self-hosted, below) or
    # "bedrock" (Amazon Bedrock, further down).
    inference_provider: Literal["ollama", "bedrock"] = "ollama"

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

    # Amazon Bedrock, used when inference_provider is "bedrock". The key is a
    # Bedrock API key (sent as a bearer token). The model id is a cross-region
    # inference profile, hence the "us." prefix.
    bedrock_key: str = ""
    bedrock_region: str = "us-west-2"
    bedrock_model_id: str = "us.meta.llama4-maverick-17b-instruct-v1:0"
    bedrock_timeout_seconds: float = 60.0
    # Calls in flight to Bedrock at once. Bounded by the account's
    # per-minute quota rather than any hardware, so higher than Ollama's.
    bedrock_max_concurrency: int = 4

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
    def model_name(self) -> str:
        """The model in use, as recorded on each extraction and review."""
        return self.bedrock_model_id if self.inference_provider == "bedrock" else self.ollama_model

    @property
    def model_max_concurrency(self) -> int:
        return self.bedrock_max_concurrency if self.inference_provider == "bedrock" else self.ollama_max_concurrency

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
