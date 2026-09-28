"""Thin wrapper around Ollama's HTTP API for label field extraction.

Deliberately the only place in the codebase that knows Ollama's request/
response shape — everything else talks to `extract_label_fields`. Swapping
the inference host (Mac now, the Linux/AMD GPU box later) is a config change
(`OLLAMA_BASE_URL`), not a code change. Other providers are sibling modules
with the same function signature (bedrock_client.py); app/inference/__init__.py
picks one from `INFERENCE_PROVIDER`. The prompt they share is in prompt.py.

IMPORTANT — why this does NOT use Ollama's `format` (JSON-schema-constrained /
grammar-guided decoding) despite that being the mechanism the AI tooling
research recommended for "guaranteed valid JSON": live testing against
qwen2.5vl found that while `format` does guarantee syntactically valid JSON,
it caused the model to silently drop or misassign several fields on a
12-field schema (net_contents and name_address came back null on every run
despite being clearly printed and legible; the Government Warning text lost
its "GOVERNMENT WARNING:" lead-in). A plain free-form transcription request
(no format, no schema) read every line of the same label perfectly. Prompting
for JSON in the system message — describing the schema in text instead of
constraining decoding with it — recovered full accuracy. The lesson: a
mechanical guarantee of *valid* JSON is not the same as a guarantee of
*complete or correctly-assigned* JSON, at least for this model/schema size.
This module trades the mechanical guarantee for a textual instruction plus
defensive parsing (extracting a JSON object from the response and retrying
once on parse failure) instead.
"""

from __future__ import annotations

import base64
import time

import httpx

from app.config import settings
from app.inference.prompt import (
    EXTRACTION_SYSTEM_PROMPT,
    LABEL_UNREADABLE,
    MODEL_NOT_SET_UP,
    MODEL_UNREACHABLE,
    RETRY_PROMPT,
    USER_PROMPT,
    ModelUnavailableError,
    extract_json_object,
)
from app.schemas import ExtractedLabelFields


async def extract_label_fields(image: bytes) -> tuple[ExtractedLabelFields, int]:
    """Runs one extraction pass over a single label image.

    Deliberately takes nothing but the image — no beverage class, no import
    status — so extraction can start the moment a photo is uploaded, before
    the user has filled in anything else. Deciding which fields matter for
    this product is the matching engine's job, not the model's.

    Returns the parsed fields and the elapsed latency in milliseconds.
    Raises ModelUnavailableError if the server can't be reached, the model
    isn't pulled, or the response still can't be parsed after one retry.
    """

    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT, "images": [base64.b64encode(image).decode("ascii")]},
    ]

    started = time.monotonic()
    last_error: Exception | None = None
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds) as client:
        for _attempt in range(2):  # one retry if the response doesn't parse
            content = await _chat(client, messages)
            try:
                fields = ExtractedLabelFields.model_validate_json(extract_json_object(content))
                latency_ms = int((time.monotonic() - started) * 1000)
                return fields, latency_ms
            except ValueError as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": RETRY_PROMPT},
                ]

    raise ModelUnavailableError(
        LABEL_UNREADABLE, f"Ollama response did not match the expected schema after a retry: {last_error}"
    )


async def _chat(client: httpx.AsyncClient, messages: list[dict]) -> str:
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "keep_alive": settings.ollama_keep_alive,
        "options": {"temperature": 0},
    }
    try:
        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Ollama returns 404 with a JSON {"error": "..."} body for problems
        # like an unpulled model — log that reason, not just the status.
        reason = exc.response.json().get("error", exc.response.text) if exc.response.content else str(exc)
        raise ModelUnavailableError(
            MODEL_NOT_SET_UP, f"Ollama at {settings.ollama_base_url} rejected the request: {reason}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ModelUnavailableError(MODEL_UNREACHABLE, f"Could not reach Ollama at {settings.ollama_base_url}: {exc!r}") from exc

    body = response.json()
    content = body.get("message", {}).get("content")
    if not content:
        raise ModelUnavailableError(LABEL_UNREADABLE, f"Ollama returned no content: {body}")
    return content


async def warm_up() -> None:
    """Asks Ollama to load the model into memory without generating anything,
    so the first real extraction doesn't pay the ~20s cold-load cost. Best
    effort: if Ollama isn't up yet, the first real request just loads it."""

    payload = {"model": settings.ollama_model, "keep_alive": settings.ollama_keep_alive}
    try:
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds) as client:
            await client.post("/api/generate", json=payload)
    except httpx.HTTPError:
        pass
