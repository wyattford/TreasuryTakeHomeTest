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
import re
import time

import httpx

from app.config import settings
from app.schemas import ExtractedLabelFields


def _describe_fields() -> str:
    """One line per field, generated from ExtractedLabelFields so the prompt
    can't drift from the schema the response is validated against. Much
    shorter than a JSON Schema dump — the model re-reads the whole system
    prompt for every image, so prompt length is paid on every extraction."""

    lines = []
    for name, field in ExtractedLabelFields.model_fields.items():
        if field.annotation == list[str]:
            kind = "list of strings, may be empty"
        else:
            kind = ("number" if "float" in str(field.annotation) else "string") + " or null"
        lines.append(f'- "{name}" ({kind}): {field.description}')
    return "\n".join(lines)


EXTRACTION_SYSTEM_PROMPT = f"""\
You are a TTB alcohol beverage label compliance assistant. You are shown one \
photo of one label from an alcohol beverage container (it may be the front \
label, a back label, or the only label) and must transcribe what is printed \
on it into a JSON object.

Transcribe text VERBATIM, including capitalization — this matters for \
compliance checks. Leave out any field that is not printed on this label — that is normal, \
since a back label usually carries only some of the fields, and a missing \
field is NOT illegible. Only list a field in illegible_fields when you can \
see its text printed on the label but cannot read it with confidence (blur, \
glare, odd angle, cut off) — never guess such a field's value. Do not infer \
or invent values that are not visibly printed on this label.

Respond with ONLY a single JSON object — no markdown code fences, no \
explanation before or after — using these keys:
{_describe_fields()}"""

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


async def extract_label_fields(image: bytes) -> tuple[ExtractedLabelFields, int]:
    """Runs one extraction pass over a single label image.

    Deliberately takes nothing but the image — no beverage class, no import
    status — so extraction can start the moment a photo is uploaded, before
    the user has filled in anything else. Deciding which fields matter for
    this product is the matching engine's job, not the model's.

    Returns the parsed fields and the elapsed latency in milliseconds.
    Raises OllamaUnavailableError if the server can't be reached, the model
    isn't pulled, or the response still can't be parsed after one retry.
    """

    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": "Transcribe this label.", "images": [_image_content(image)]},
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
        "keep_alive": settings.ollama_keep_alive,
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
