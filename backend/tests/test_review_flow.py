"""API-level tests of the upload-first flow: images are uploaded (and start
extracting) before the review is submitted. The vision model is stubbed out,
so these run without Ollama."""

import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import extraction_service, storage
from app.db import Base, engine
from app.inference.ollama_client import OllamaUnavailableError
from app.main import app
from app.schemas import ExtractedLabelFields

WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during "
    "pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)
FRONT_FIELDS = ExtractedLabelFields(
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    abv_percent=45.0,
    proof=90,
    net_contents="750 mL",
)
BACK_FIELDS = ExtractedLabelFields(name_address="Old Tom Distillery, Louisville, KY", government_warning_text=WARNING)


def _png(color: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (60, 40), color).save(out, format="PNG")
    return out.getvalue()


FRONT_PNG = _png("white")
BACK_PNG = _png("black")


@pytest.fixture
def client(tmp_path, monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "BACKEND_DIR", tmp_path)
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    calls = {"count": 0, "fail": False}

    async def fake_extract(image: bytes):
        calls["count"] += 1
        await asyncio.sleep(0.05)
        if calls["fail"]:
            raise OllamaUnavailableError("Ollama is down")
        # White image = front label, black = back label.
        is_front = Image.open(io.BytesIO(image)).getpixel((0, 0))[0] > 128
        return (FRONT_FIELDS if is_front else BACK_FIELDS), 50

    monkeypatch.setattr(extraction_service, "extract_label_fields", fake_extract)
    with TestClient(app) as test_client:
        test_client.calls = calls
        yield test_client


def _upload(client, png: bytes) -> dict:
    response = client.post("/extractions", files={"image": ("label.png", png, "image/png")})
    assert response.status_code == 202, response.text
    return response.json()


def test_upload_then_review_with_extraction_ids(client):
    front = _upload(client, FRONT_PNG)
    back = _upload(client, BACK_PNG)
    assert front["status"] == "pending"

    done = client.get(f"/extractions/{front['id']}", params={"wait": 5}).json()
    assert done["status"] == "done"
    assert done["extracted_fields"]["brand_name"] == "OLD TOM DISTILLERY"

    response = client.post(
        "/reviews",
        data={
            "front_extraction_id": front["id"],
            "back_extraction_id": back["id"],
            "beverage_class": "distilled_spirits",
            "brand_name": "Old Tom Distillery",
            "abv": "45",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["overall_status"] == "clear", result["comparisons"]
    assert result["field_sources"]["government_warning_text"] == "back"
    assert result["field_sources"]["brand_name"] == "front"
    assert {c["field_name"] for c in result["comparisons"]} >= {"brand_name", "proof", "government_warning"}


def test_reuploading_same_image_reuses_extraction(client):
    first = _upload(client, FRONT_PNG)
    client.get(f"/extractions/{first['id']}", params={"wait": 5})
    second = _upload(client, FRONT_PNG)
    assert second["id"] == first["id"]
    assert second["status"] == "done"


def test_review_with_files_still_works(client):
    response = client.post(
        "/reviews",
        files={"front": ("f.png", FRONT_PNG, "image/png"), "back": ("b.png", BACK_PNG, "image/png")},
        data={"beverage_class": "distilled_spirits"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["overall_status"] == "clear"


def test_failed_extraction_is_retried_when_review_needs_it(client):
    client.calls["fail"] = True
    front = _upload(client, _png("white"))
    assert client.get(f"/extractions/{front['id']}", params={"wait": 5}).json()["status"] == "error"

    client.calls["fail"] = False
    response = client.post("/reviews", data={"front_extraction_id": front["id"], "beverage_class": "distilled_spirits"})
    assert response.status_code == 200, response.text


def test_review_fails_cleanly_when_model_is_down(client):
    client.calls["fail"] = True
    response = client.post("/reviews", files={"front": ("f.png", _png("gray"), "image/png")}, data={"beverage_class": "wine"})
    assert response.status_code == 502
    assert "Ollama is down" in response.json()["detail"]


def test_non_image_upload_is_rejected(client):
    response = client.post("/extractions", files={"image": ("x.png", b"not an image", "image/png")})
    assert response.status_code == 422


def test_oversized_upload_is_rejected(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    response = client.post("/extractions", files={"image": ("big.png", FRONT_PNG, "image/png")})
    assert response.status_code == 413


def test_decision_is_recorded_and_returned_with_review(client):
    review = client.post(
        "/reviews", files={"front": ("f.png", FRONT_PNG, "image/png")}, data={"beverage_class": "distilled_spirits"}
    ).json()
    application_id = review["application"]["id"]

    response = client.put(f"/reviews/{application_id}/decision", json={"decision": "reject", "note": "  bad warning "})
    assert response.status_code == 200
    assert response.json()["note"] == "bad warning"

    client.put(f"/reviews/{application_id}/decision", json={"decision": "accept"})
    fetched = client.get(f"/reviews/{application_id}").json()
    assert fetched["decision"]["decision"] == "accept"
