import os
import tempfile

# Point the app at a throwaway database before anything imports app.config,
# and don't try to reach Ollama on startup.
_TMP = tempfile.mkdtemp(prefix="ttb-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["OLLAMA_WARMUP_ON_STARTUP"] = "false"

import asyncio  # noqa: E402
import io  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import extraction_service, storage  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.inference.ollama_client import OllamaUnavailableError  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import ExtractedLabelFields  # noqa: E402

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


def png(color) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (60, 40), color).save(out, format="PNG")
    return out.getvalue()


FRONT_PNG = png("white")
BACK_PNG = png("black")
# The stubbed model can't read this one.
UNREADABLE_PNG = png("red")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient with a fresh database and uploads directory, and the
    vision model stubbed out: light images read as the front label, dark
    ones as the back label, red ones fail. Set ``client.calls["fail"]`` to
    make every read fail."""

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "BACKEND_DIR", tmp_path)
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    calls = {"count": 0, "fail": False, "order": []}

    async def fake_extract(image: bytes):
        calls["count"] += 1
        await asyncio.sleep(0.05)
        red, green, _ = Image.open(io.BytesIO(image)).convert("RGB").getpixel((0, 0))
        calls["order"].append((red, green))
        if calls["fail"] or (red > 200 and green < 50):
            raise OllamaUnavailableError("Ollama is down")
        return (FRONT_FIELDS if red > 128 else BACK_FIELDS), 50

    monkeypatch.setattr(extraction_service, "extract_label_fields", fake_extract)
    with TestClient(app) as test_client:
        test_client.calls = calls
        yield test_client
