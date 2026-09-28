"""Label field extraction through Amazon Bedrock's Converse API.

The hosted counterpart to ollama_client.py, for deployments with no GPU of
their own. It sends the same prompt and parses the reply the same way, so
the two are interchangeable behind `INFERENCE_PROVIDER`. The default model is
an open-weight one (Llama 4 Maverick): the same weights could be served from
an agency's own cloud account or hardware, which is the point of not relying
on a vendor-only model.

Authenticates with a Bedrock API key sent as a bearer token, over plain
HTTPS, so there's no AWS SDK dependency. A deployment running inside AWS
would use an IAM role instead.
"""

from __future__ import annotations

import asyncio
import base64
import time

import httpx

from app.config import settings
from app.inference.prompt import (
    EXTRACTION_SYSTEM_PROMPT,
    RETRY_PROMPT,
    USER_PROMPT,
    ModelUnavailableError,
    extract_json_object,
)
from app.schemas import ExtractedLabelFields

# Bedrock answers 429 when the account's per-minute quota is used up and 503
# when the model is briefly overloaded; both are worth a short wait and retry.
_RETRYABLE_STATUSES = {429, 503}
_BACKOFF_SECONDS = (1.0, 3.0)


async def extract_label_fields(image: bytes) -> tuple[ExtractedLabelFields, int]:
    """Same contract as ollama_client.extract_label_fields: one pass over one
    normalized (JPEG) label image, the parsed fields and elapsed milliseconds
    back, ModelUnavailableError if no usable answer comes back."""

    if not settings.bedrock_key:
        raise ModelUnavailableError("Bedrock is selected but BEDROCK_KEY isn't set.")

    messages = [
        {
            "role": "user",
            "content": [
                {"image": {"format": "jpeg", "source": {"bytes": base64.b64encode(image).decode("ascii")}}},
                {"text": USER_PROMPT},
            ],
        }
    ]

    started = time.monotonic()
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        base_url=f"https://bedrock-runtime.{settings.bedrock_region}.amazonaws.com",
        headers={"Authorization": f"Bearer {settings.bedrock_key}"},
        timeout=settings.bedrock_timeout_seconds,
    ) as client:
        for _attempt in range(2):  # one retry if the response doesn't parse
            content = await _converse(client, messages)
            try:
                fields = ExtractedLabelFields.model_validate_json(extract_json_object(content))
                return fields, int((time.monotonic() - started) * 1000)
            except ValueError as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": [{"text": content}]},
                    {"role": "user", "content": [{"text": RETRY_PROMPT}]},
                ]

    raise ModelUnavailableError(f"Bedrock response did not match the expected schema after a retry: {last_error}")


async def _converse(client: httpx.AsyncClient, messages: list[dict]) -> str:
    payload = {
        "system": [{"text": EXTRACTION_SYSTEM_PROMPT}],
        "messages": messages,
        "inferenceConfig": {"temperature": 0, "maxTokens": 2000},
    }
    url = f"/model/{settings.bedrock_model_id}/converse"

    for backoff in (*_BACKOFF_SECONDS, None):
        try:
            response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise ModelUnavailableError(f"Could not reach Bedrock in {settings.bedrock_region}: {exc}") from exc
        if response.status_code in _RETRYABLE_STATUSES and backoff is not None:
            await asyncio.sleep(backoff)
            continue
        break

    if response.status_code != 200:
        # Bedrock errors are JSON {"message": "..."}: an unknown model id,
        # a key without access, a quota exceeded.
        try:
            reason = response.json().get("message", response.text)
        except ValueError:
            reason = response.text
        raise ModelUnavailableError(f"Bedrock rejected the request ({response.status_code}): {reason}")

    body = response.json()
    try:
        return next(block["text"] for block in body["output"]["message"]["content"] if "text" in block)
    except (KeyError, StopIteration) as exc:
        raise ModelUnavailableError(f"Bedrock returned no text (stopReason={body.get('stopReason')})") from exc


async def warm_up() -> None:
    """Nothing to load: Bedrock's on-demand models are always resident."""
