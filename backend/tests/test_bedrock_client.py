import asyncio
import json

import httpx
import pytest

from app.config import settings
from app.inference import ModelUnavailableError, bedrock_client
from app.inference.prompt import MODEL_NOT_SET_UP

FIELDS_JSON = '{"brand_name": "OLD TOM DISTILLERY", "abv_percent": 45.0, "other_disclosures": [], "illegible_fields": []}'


def reply(text: str) -> httpx.Response:
    return httpx.Response(200, json={"output": {"message": {"role": "assistant", "content": [{"text": text}]}}})


@pytest.fixture
def bedrock(monkeypatch):
    """Routes the client's HTTP calls to ``handler`` (set by each test) and
    records every request it makes."""

    monkeypatch.setattr(settings, "bedrock_key", "test-key")
    monkeypatch.setattr(settings, "bedrock_model_id", "us.test-model")
    real_sleep = asyncio.sleep
    monkeypatch.setattr(bedrock_client.asyncio, "sleep", lambda _: real_sleep(0))
    state = {"requests": [], "responses": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["responses"].pop(0)

    real_client = httpx.AsyncClient

    def client_with_mock(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bedrock_client.httpx, "AsyncClient", client_with_mock)
    return state


def extract():
    return asyncio.run(bedrock_client.extract_label_fields(b"jpeg-bytes"))


def test_sends_the_shared_prompt_and_parses_a_fenced_reply(bedrock):
    bedrock["responses"] = [reply(f"```json\n{FIELDS_JSON}\n```")]

    fields, _ = extract()

    assert fields.brand_name == "OLD TOM DISTILLERY"
    request = bedrock["requests"][0]
    assert request.url.path == "/model/us.test-model/converse"
    assert request.headers["Authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["system"][0]["text"].startswith("You are a TTB alcohol beverage label compliance assistant")
    assert body["inferenceConfig"]["temperature"] == 0


def test_retries_once_when_the_reply_is_not_json(bedrock):
    bedrock["responses"] = [reply("Sorry, here is the label."), reply(FIELDS_JSON)]

    fields, _ = extract()

    assert fields.abv_percent == 45.0
    retry = json.loads(bedrock["requests"][1].content)
    assert [m["role"] for m in retry["messages"]] == ["user", "assistant", "user"]


def test_waits_and_retries_when_throttled(bedrock):
    bedrock["responses"] = [httpx.Response(429, json={"message": "Too many requests"}), reply(FIELDS_JSON)]

    fields, _ = extract()

    assert fields.brand_name == "OLD TOM DISTILLERY"
    assert len(bedrock["requests"]) == 2


def test_a_rejected_request_tells_the_agent_plainly_and_logs_bedrocks_reason(bedrock):
    bedrock["responses"] = [httpx.Response(403, json={"message": "You don't have access to the model"})]

    with pytest.raises(ModelUnavailableError) as raised:
        extract()

    assert str(raised.value) == MODEL_NOT_SET_UP
    assert "403" in raised.value.detail and "don't have access" in raised.value.detail


def test_still_throttled_after_retries_says_busy(bedrock):
    bedrock["responses"] = [httpx.Response(429, json={"message": "Too many requests"})] * 3

    with pytest.raises(ModelUnavailableError, match="busy"):
        extract()


def test_refuses_to_call_without_a_key(bedrock, monkeypatch):
    monkeypatch.setattr(settings, "bedrock_key", "")

    with pytest.raises(ModelUnavailableError) as raised:
        extract()
    assert "BEDROCK_KEY" in raised.value.detail
    assert bedrock["requests"] == []
