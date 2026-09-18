"""Thin wrapper around Ollama's HTTP API for label field extraction.

Deliberately the only place in the codebase that knows Ollama's request/
response shape — everything else talks to `extract_label_fields`. Swapping
the inference host (Mac now, the Linux/AMD GPU box later) is a config change
(`OLLAMA_BASE_URL`), not a code change. Swapping the whole *approach* (e.g.
falling back to an OCR + small-LLM pipeline per the AI tooling research) means
adding a sibling module with the same function signature, not touching this
one or its callers.

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
import json
import re
import time

import httpx

from app.config import settings
from app.schemas import ExtractedLabelFields

_SCHEMA_DESCRIPTION = json.dumps(ExtractedLabelFields.model_json_schema(), indent=2)

EXTRACTION_SYSTEM_PROMPT = f"""\
You are a TTB alcohol beverage label compliance assistant. You are shown one \
or two photos of an alcohol beverage label (a front label, and optionally a \
back label) and must transcribe what is printed on it into a JSON object.

Transcribe text VERBATIM, including capitalization — this matters for \
compliance checks. If a field is not visible on either image, use null. \
If a field is present but you cannot read it with confidence (blur, glare, \
odd angle, cut off), use null for it AND add its field name to \
illegible_fields rather than guessing. Do not infer or invent values that \
are not visibly printed on the label.

Respond with ONLY a single JSON object — no markdown code fences, no \
explanation before or after — matching this JSON Schema exactly:
{_SCHEMA_DESCRIPTION}"""

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class OllamaUnavailableError(RuntimeError):
    """Raised when Ollama can't be reached or returns an unusable response."""


def _image_content(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("ascii")


def _extract_json_object(content: str) -> str:
    """Ollama is instructed to return bare JSON, but models sometimes wrap it
    in prose or code fences anyway — pull out the outermost {...} block."""

    match = _JSON_OBJECT_RE.search(content)
    return match.group(0) if match else content


async def extract_label_fields(
    *,
    front_image: bytes,
    back_image: bytes | None,
    beverage_class: str,
    imported: bool,
) -> tuple[ExtractedLabelFields, int]:
    """Runs one extraction pass over a label's image(s).

    Returns the parsed fields and the elapsed latency in milliseconds.
    Raises OllamaUnavailableError if the server can't be reached, the model
    isn't pulled, or the response still can't be parsed after one retry.
    """

    images = [_image_content(front_image)]
    if back_image is not None:
        images.append(_image_content(back_image))

    origin_note = (
        "This is an imported product; look for a country of origin statement."
        if imported
        else "This is a domestic product; leave country_of_origin null."
    )
    image_count_note = (
        "Two images are provided: the front label, then the back label."
        if back_image
        else "One image is provided: the front (only) label."
    )
    user_prompt = f"Beverage class: {beverage_class}. {origin_note} {image_count_note}"

    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt, "images": images},
    ]

    started = time.monotonic()
    last_error: Exception | None = None
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds) as client:
        for _attempt in range(2):  # one retry if the response doesn't parse
            content = await _chat(client, messages)
            try:
                fields = ExtractedLabelFields.model_validate_json(_extract_json_object(content))
                latency_ms = int((time.monotonic() - started) * 1000)
                return fields, latency_ms
            except ValueError as exc:
                last_error = exc
                retry_prompt = "That wasn't valid JSON matching the schema. Respond with ONLY the corrected JSON object."
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": retry_prompt},
                ]

    raise OllamaUnavailableError(f"Ollama response did not match the expected schema after a retry: {last_error}")


async def _chat(client: httpx.AsyncClient, messages: list[dict]) -> str:
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Ollama returns 404 with a JSON {"error": "..."} body for problems
        # like an unpulled model — surface that reason, not just the status.
        reason = exc.response.json().get("error", exc.response.text) if exc.response.content else str(exc)
        raise OllamaUnavailableError(f"Ollama at {settings.ollama_base_url} rejected the request: {reason}") from exc
    except httpx.HTTPError as exc:
        raise OllamaUnavailableError(f"Could not reach Ollama at {settings.ollama_base_url}: {exc}") from exc

    body = response.json()
    content = body.get("message", {}).get("content")
    if not content:
        raise OllamaUnavailableError(f"Ollama returned no content: {body}")
    return content
