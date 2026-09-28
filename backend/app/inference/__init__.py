"""The vision model, whichever provider serves it.

Callers use `extract_label_fields` and `warm_up` from here; `INFERENCE_PROVIDER`
decides whether they go to Ollama (self-hosted) or Amazon Bedrock. The choice
is read on each call, so tests and scripts can switch it through settings.
"""

from __future__ import annotations

from app.config import settings
from app.inference import bedrock_client, ollama_client
from app.inference.prompt import EXTRACTION_SYSTEM_PROMPT, ModelUnavailableError
from app.schemas import ExtractedLabelFields

__all__ = ["EXTRACTION_SYSTEM_PROMPT", "ModelUnavailableError", "extract_label_fields", "warm_up"]


def _client():
    return bedrock_client if settings.inference_provider == "bedrock" else ollama_client


async def extract_label_fields(image: bytes) -> tuple[ExtractedLabelFields, int]:
    return await _client().extract_label_fields(image)


async def warm_up() -> None:
    await _client().warm_up()
