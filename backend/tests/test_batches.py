"""API tests for batch review, with the vision model stubbed out (see
conftest.py): create the batch, upload + attach each row's images, let the
background runner review them, then read progress and export."""

import csv
import io
import time

from app.batch_service import resume_batches
from tests.conftest import BACK_PNG, UNREADABLE_PNG, png


def _upload(client, image: bytes, priority: str = "batch") -> str:
    response = client.post("/extractions", params={"priority": priority}, files={"image": ("x.png", image, "image/png")})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def _create(client, rows: list[dict], name: str = "Harbor Imports — October") -> dict:
    response = client.post("/batches", json={"name": name, "rows": rows})
    assert response.status_code == 201, response.text
    return response.json()


def _attach(client, batch_id: str, item_id: str, front: bytes, back: bytes | None = None):
    body = {"front_extraction_id": _upload(client, front)}
    if back is not None:
        body["back_extraction_id"] = _upload(client, back)
    return client.put(f"/batches/{batch_id}/items/{item_id}/images", json=body)


def _wait_until_settled(client, batch_id: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        batch = client.get(f"/batches/{batch_id}").json()
        if batch["counts"]["queued"] == 0:
            return batch
        time.sleep(0.05)
    raise AssertionError(f"batch still running: {batch['counts']}")


def _row(n: int, **overrides) -> dict:
    row = {
        "reference": f"HI-{n:03d}",
        "front_image": f"HI-{n:03d}_front.jpg",
        "back_image": f"HI-{n:03d}_back.jpg",
        "beverage_class": "distilled_spirits",
    }
    row.update(overrides)
    return row


def _front(n: int) -> bytes:
    # Distinct light images, so each row gets its own extraction.
    return png((255, 255, 255 - n))


def test_batch_lifecycle(client):
    rows = [_row(1, brand_name="Old Tom Distillery"), _row(2, brand_name="Some Other Brand"), _row(3, back_image=None)]
    batch = _create(client, rows)
    assert batch["status"] == "uploading"
    assert [i["status"] for i in batch["items"]] == ["awaiting_images"] * 3

    items = batch["items"]
    assert _attach(client, batch["id"], items[0]["id"], _front(1), BACK_PNG).status_code == 200
    assert _attach(client, batch["id"], items[1]["id"], _front(2), BACK_PNG).status_code == 200
    assert _attach(client, batch["id"], items[2]["id"], _front(3)).status_code == 200

    batch = _wait_until_settled(client, batch["id"])
    assert batch["status"] == "done"
    by_ref = {i["reference"]: i for i in batch["items"]}
    assert by_ref["HI-001"]["overall_status"] == "clear"
    assert by_ref["HI-002"]["overall_status"] == "flagged"  # declared brand doesn't match the label
    assert by_ref["HI-003"]["overall_status"] == "flagged"  # no back label: warning + name/address missing
    assert batch["counts"] == {
        "awaiting_images": 0,
        "queued": 0,
        "clear": 1,
        "flagged": 2,
        "error": 0,
        "skipped": 0,
        "decided": 0,
    }

    # Items open and take decisions through the ordinary review endpoints.
    application_id = by_ref["HI-002"]["application_id"]
    assert client.get(f"/reviews/{application_id}").status_code == 200
    client.put(f"/reviews/{application_id}/decision", json={"decision": "reject", "note": "wrong brand"})
    batch = client.get(f"/batches/{batch['id']}").json()
    assert batch["counts"]["decided"] == 1

    export = list(csv.DictReader(io.StringIO(client.get(f"/batches/{batch['id']}/export.csv").text)))
    assert [r["reference"] for r in export] == ["HI-001", "HI-002", "HI-003"]
    assert export[0]["result"] == "Everything checks out"
    assert export[1]["brand_name_status"] == "mismatch"
    assert export[1]["decision"] == "reject"
    assert export[1]["decision_note"] == "wrong brand"


def test_unreadable_row_does_not_stop_the_batch_and_can_be_retried(client, monkeypatch):
    batch = _create(client, [_row(1, back_image=None), _row(2, back_image=None)])
    items = batch["items"]
    _attach(client, batch["id"], items[0]["id"], UNREADABLE_PNG)
    _attach(client, batch["id"], items[1]["id"], _front(2))

    batch = _wait_until_settled(client, batch["id"])
    assert [i["status"] for i in batch["items"]] == ["error", "reviewed"]
    assert "Ollama is down" in batch["items"][0]["error_message"]

    # Retrying re-reads the image; make the stub succeed this time.
    from app import extraction_service
    from tests.conftest import FRONT_FIELDS

    async def now_readable(image):
        return FRONT_FIELDS, 10

    monkeypatch.setattr(extraction_service, "extract_label_fields", now_readable)
    assert client.post(f"/batches/{batch['id']}/retry-failed").status_code == 200
    batch = _wait_until_settled(client, batch["id"])
    assert [i["status"] for i in batch["items"]] == ["reviewed", "reviewed"]


def test_cancel_skips_rows_not_yet_reviewed(client):
    batch = _create(client, [_row(1, back_image=None), _row(2, back_image=None)])
    _attach(client, batch["id"], batch["items"][0]["id"], _front(1))
    _wait_until_settled(client, batch["id"])

    batch = client.post(f"/batches/{batch['id']}/cancel").json()
    assert batch["status"] == "cancelled"
    assert [i["status"] for i in batch["items"]] == ["reviewed", "skipped"]
    assert _attach(client, batch["id"], batch["items"][1]["id"], _front(2)).status_code == 409


def test_attach_rejects_back_image_the_spreadsheet_did_not_list(client):
    batch = _create(client, [_row(1, back_image=None)])
    response = _attach(client, batch["id"], batch["items"][0]["id"], _front(1), BACK_PNG)
    assert response.status_code == 409


def test_invalid_rows_are_rejected_up_front(client):
    response = client.post("/batches", json={"name": "x", "rows": [_row(1, beverage_class="cider")]})
    assert response.status_code == 422


def test_queued_rows_resume_after_restart(client):
    batch = _create(client, [_row(1, back_image=None)])
    item = batch["items"][0]
    # Simulate a row that was queued when the process died: attach its
    # images directly in the database, with no runner started.
    from app.db import SessionLocal
    from app.models import BatchItem

    extraction_id = _upload(client, _front(1))
    with SessionLocal() as db:
        row = db.get(BatchItem, item["id"])
        row.front_extraction_id = extraction_id
        row.status = "queued"
        db.commit()
    assert client.get(f"/batches/{batch['id']}").json()["status"] == "running"

    client.portal.call(resume_batches)
    assert _wait_until_settled(client, batch["id"])["status"] == "done"


def test_batch_images_wait_behind_interactive_ones(client):
    # One model slot; a batch image is being read and more are queued when
    # an agent uploads a single label. The agent's image must be read next.
    from app import extraction_service
    from app.priority_gate import PriorityGate

    extraction_service._ollama_gate = PriorityGate(1)
    try:
        for n in range(4):
            _upload(client, png((255, 255 - n, 255)), priority="batch")
        _upload(client, png((255, 200, 100)), priority="interactive")
        deadline = time.monotonic() + 5
        while len(client.calls["order"]) < 5 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert client.calls["order"][1] == (255, 200)
    finally:
        extraction_service._ollama_gate = None


def test_more_waiting_reviews_than_database_connections_does_not_deadlock(client, monkeypatch):
    # Regression: every review waiting on its extraction used to hold a
    # pooled database connection for the whole wait. With more rows waiting
    # than the pool has connections (5 + 10 overflow), the next checkout
    # blocked the event loop — which the waiting reviews needed to finish.
    import asyncio

    from app import extraction_service
    from app.db import engine
    from tests.conftest import FRONT_FIELDS

    async def slow_read(image):
        await asyncio.sleep(0.2)  # slow enough that reviews pile up waiting
        return FRONT_FIELDS, 200

    monkeypatch.setattr(extraction_service, "extract_label_fields", slow_read)
    rows = [_row(n, back_image=None) for n in range(1, 25)]
    assert len(rows) > engine.pool.size() + engine.pool._max_overflow
    batch = _create(client, rows)
    for n, item in enumerate(batch["items"], start=1):
        assert _attach(client, batch["id"], item["id"], _front(n)).status_code == 200
    batch = _wait_until_settled(client, batch["id"], timeout=20)
    assert batch["counts"]["clear"] + batch["counts"]["flagged"] == 24
