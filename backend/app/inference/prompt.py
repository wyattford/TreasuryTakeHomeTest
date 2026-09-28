"""What every model client shares: the extraction prompt, the retry
instruction, pulling a JSON object out of a reply, and the error callers
catch. Keeping the prompt here means switching providers never changes what
the model is asked, and the cache key (see app/extraction_service.py) only
changes when the prompt or model does."""

from __future__ import annotations

import re

from app.schemas import ExtractedLabelFields


class ModelUnavailableError(RuntimeError):
    """Raised when the vision model can't be reached or returns an unusable
    response. The message is shown to the agent as-is, so it's one of the
    plain-language messages below; ``detail`` is the technical reason, for
    the server log."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.detail = detail


# What the agent is told. None of these name a vendor, a status code, or a
# setting: the agent can't act on those, and whoever can reads the log.
MODEL_NOT_SET_UP = "The label reader isn't available right now. Please try again later, or let your system administrator know."
MODEL_UNREACHABLE = "The label reader couldn't be reached. Please try again in a minute."
MODEL_BUSY = "The label reader is busy right now. Please try again in a minute."
LABEL_UNREADABLE = "This photo couldn't be read. Try a sharper, straight-on photo of the label."


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

USER_PROMPT = "Transcribe this label."

RETRY_PROMPT = "That wasn't valid JSON matching the schema. Respond with ONLY the corrected JSON object."

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json_object(content: str) -> str:
    """Models are instructed to return bare JSON, but sometimes wrap it in
    prose or code fences anyway — pull out the outermost {...} block."""

    match = _JSON_OBJECT_RE.search(content)
    return match.group(0) if match else content
