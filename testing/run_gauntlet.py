#!/usr/bin/env python3
"""Runs the test gauntlet against a live backend: submits every fixture
case's label image(s) + declared fields to `POST /reviews`, and compares the
real (OCR + matching-engine) verdicts against each case's precomputed
expected verdicts.

Requires the FastAPI backend (and Ollama, with the vision model pulled) to
actually be running — this is deliberately an end-to-end test of the real
extraction pipeline, not a mock.

Usage:
    python run_gauntlet.py
    python run_gauntlet.py --base-url http://localhost:8000
    python run_gauntlet.py --only blur_correct rotate_incorrect
    python run_gauntlet.py --tag distortion
    python run_gauntlet.py --batch        # submit every case as one batch instead
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

TESTING_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = TESTING_DIR / "fixtures" / "manifest.json"
RESULTS_DIR = TESTING_DIR / "results"

# Declared fields whose value, when None, must be omitted from the form
# entirely rather than sent as the literal string "None" — FastAPI's
# Form(None) defaults kick in only when the key is absent.
_OPTIONAL_FIELDS = {"fanciful_name", "abv", "country_of_origin", "appellation", "sulfite_declaration"}


def _load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"No manifest at {MANIFEST_PATH} — run generate_fixtures.py first.")
    return json.loads(MANIFEST_PATH.read_text())


def _form_data(declared: dict) -> dict:
    data = {}
    for key, value in declared.items():
        if value is None:
            if key in _OPTIONAL_FIELDS:
                continue
            value = ""
        if isinstance(value, bool):
            value = "true" if value else "false"
        data[key] = value
    return data


def submit_case(client: httpx.Client, case: dict, *, retries: int = 2) -> dict:
    """POSTs one case. Retries a bounded number of times on a 502, since that
    status means the backend's own model call failed transiently (a cold
    model load, a request-queue timeout under load) rather than anything
    wrong with the case itself — see ModelUnavailableError in
    app/inference/prompt.py."""

    front_path = TESTING_DIR / case["front_image"]
    back_path = TESTING_DIR / case["back_image"]
    last_error: httpx.HTTPStatusError | None = None
    for attempt in range(retries + 1):
        with front_path.open("rb") as front_fh, back_path.open("rb") as back_fh:
            files = {
                "front": (front_path.name, front_fh, "image/png"),
                "back": (back_path.name, back_fh, "image/png"),
            }
            response = client.post("/reviews", data=_form_data(case["declared"]), files=files)
        if response.status_code != 502:
            response.raise_for_status()
            return response.json()
        last_error = httpx.HTTPStatusError(f"502 on attempt {attempt + 1}", request=response.request, response=response)
        if attempt < retries:
            time.sleep(2.0)
    raise last_error


def run_as_batch(client: httpx.Client, cases: list[dict], *, poll_seconds: float = 2.0) -> dict[str, dict]:
    """Submits every case as rows of one batch through the batch API (create,
    upload + attach each row's images, wait for the background runner), then
    fetches each row's review. Returns case id -> review result, or
    {"error": ...} for rows that failed."""

    rows = [
        {
            **case["declared"],
            "reference": case["id"],
            "front_image": f"{case['id']}_front.png",
            "back_image": f"{case['id']}_back.png",
        }
        for case in cases
    ]
    response = client.post("/batches", json={"name": f"Gauntlet {time.strftime('%Y-%m-%d %H:%M')}", "rows": rows})
    response.raise_for_status()
    batch = response.json()
    by_reference = {item["reference"]: item for item in batch["items"]}

    started = time.monotonic()
    for case in cases:
        ids = []
        for key in ("front_image", "back_image"):
            path = TESTING_DIR / case[key]
            with path.open("rb") as fh:
                uploaded = client.post(
                    "/extractions", params={"priority": "batch"}, files={"image": (path.name, fh, "image/png")}
                )
            uploaded.raise_for_status()
            ids.append(uploaded.json()["id"])
        item_id = by_reference[case["id"]]["id"]
        attach = client.put(
            f"/batches/{batch['id']}/items/{item_id}/images",
            json={"front_extraction_id": ids[0], "back_extraction_id": ids[1]},
        )
        attach.raise_for_status()
    print(f"Uploaded {len(cases)} applications in {time.monotonic() - started:.1f}s; waiting for the batch ...")

    while True:
        batch = client.get(f"/batches/{batch['id']}").json()
        counts = batch["counts"]
        finished = counts["clear"] + counts["flagged"] + counts["error"]
        print(f"  {finished}/{batch['total']} reviewed", end="\r", flush=True)
        if batch["status"] != "running":
            break
        time.sleep(poll_seconds)
    elapsed = time.monotonic() - started
    print(f"\nBatch finished in {elapsed:.1f}s ({2 * len(cases) / elapsed * 60:.1f} images/min, including cached reads)")

    results: dict[str, dict] = {}
    for item in batch["items"]:
        if item["status"] == "reviewed":
            review = client.get(f"/reviews/{item['application_id']}")
            review.raise_for_status()
            results[item["reference"]] = review.json()
        else:
            results[item["reference"]] = {"error": item["error_message"] or item["status"]}
    return results


def evaluate_case(case: dict, actual: dict) -> dict:
    expected = case["expected"]
    actual_fields = {f["field_name"]: f for f in actual["comparisons"]}

    field_results = []
    all_fields_ok = True
    for expected_field in expected["fields"]:
        name = expected_field["field_name"]
        actual_field = actual_fields.get(name)
        ok = actual_field is not None and actual_field["status"] == expected_field["status"]
        all_fields_ok = all_fields_ok and ok
        field_results.append(
            {
                "field_name": name,
                "expected_status": expected_field["status"],
                "actual_status": actual_field["status"] if actual_field else None,
                "actual_extracted_value": actual_field["extracted_value"] if actual_field else None,
                "ok": ok,
            }
        )

    expected_field_names = {f["field_name"] for f in expected["fields"]}
    extra_fields = [f for name, f in actual_fields.items() if name not in expected_field_names]
    extra_actual_fields = [{"field_name": f["field_name"], "status": f["status"], "detail": f["detail"]} for f in extra_fields]

    overall_ok = actual["overall_status"] == expected["overall_status"]
    passed = overall_ok and all_fields_ok

    return {
        "id": case["id"],
        "description": case["description"],
        "tags": case["tags"],
        "distortion": case["distortion"],
        "passed": passed,
        "expected_overall_status": expected["overall_status"],
        "actual_overall_status": actual["overall_status"],
        "latency_ms": actual.get("latency_ms"),
        "field_results": field_results,
        "extra_actual_fields": extra_actual_fields,
    }


def print_result(result: dict) -> None:
    mark = "PASS" if result["passed"] else "FAIL"
    known = " [known limitation]" if "known_limitation" in result["tags"] else ""
    latency = f", {result['latency_ms']}ms" if result.get("latency_ms") is not None else ""
    print(f"[{mark}] {result['id']}{known}  ({result['distortion']}{latency})")
    if "error" in result:
        print(f"       {result['description']}")
        print(f"       error: {result['error']}")
        return
    if not result["passed"]:
        print(f"       {result['description']}")
        if result["actual_overall_status"] != result["expected_overall_status"]:
            print(
                f"       overall_status: expected={result['expected_overall_status']!r} "
                f"actual={result['actual_overall_status']!r}"
            )
        for field in result["field_results"]:
            if not field["ok"]:
                print(
                    f"       {field['field_name']}: expected={field['expected_status']!r} "
                    f"actual={field['actual_status']!r} (label read as: {field['actual_extracted_value']!r})"
                )
        for extra in result["extra_actual_fields"]:
            print(f"       extra flag from model: {extra['field_name']} -> {extra['status']} ({extra['detail']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL (default: %(default)s)")
    parser.add_argument("--only", nargs="+", metavar="CASE_ID", help="Only run these case ids.")
    parser.add_argument("--tag", help="Only run cases with this tag.")
    parser.add_argument("--timeout", type=float, default=90.0, help="Per-request timeout in seconds (default: %(default)s)")
    parser.add_argument("--batch", action="store_true", help="Submit all cases as one batch through the batch API.")
    args = parser.parse_args()

    cases = _load_manifest()
    if args.only:
        ids = set(args.only)
        cases = [c for c in cases if c["id"] in ids]
        missing = ids - {c["id"] for c in cases}
        if missing:
            raise SystemExit(f"Unknown case id(s): {sorted(missing)}")
    if args.tag:
        cases = [c for c in cases if args.tag in c["tags"]]
        if not cases:
            raise SystemExit(f"No cases tagged {args.tag!r}.")

    print(f"Running {len(cases)} case(s) against {args.base_url} ...\n")

    results = []
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        if args.batch:
            try:
                batch_results = run_as_batch(client, cases)
            except httpx.ConnectError as exc:
                raise SystemExit(f"\nCould not reach the backend at {args.base_url}. Is it running?\n({exc})") from exc
            for case in cases:
                actual = batch_results[case["id"]]
                if "error" in actual:
                    results.append(
                        {
                            "id": case["id"],
                            "description": case["description"],
                            "tags": case["tags"],
                            "distortion": case["distortion"],
                            "passed": False,
                            "error": actual["error"],
                        }
                    )
                else:
                    results.append(evaluate_case(case, actual))
        for i, case in enumerate([] if args.batch else cases, 1):
            print(f"({i}/{len(cases)}) {case['id']} ...", end=" ", flush=True)
            started = time.monotonic()
            try:
                actual = submit_case(client, case)
            except httpx.ConnectError as exc:
                raise SystemExit(
                    f"\nCould not reach the backend at {args.base_url}. Is it running?\n"
                    f"  cd ../backend && uv run uvicorn app.main:app --reload\n({exc})"
                ) from exc
            except httpx.HTTPStatusError as exc:
                print(f"HTTP {exc.response.status_code}")
                results.append(
                    {
                        "id": case["id"],
                        "description": case["description"],
                        "tags": case["tags"],
                        "distortion": case["distortion"],
                        "passed": False,
                        "error": f"HTTP {exc.response.status_code}: {exc.response.text}",
                    }
                )
                continue
            elapsed = time.monotonic() - started
            print(f"done in {elapsed:.1f}s")
            results.append(evaluate_case(case, actual))

    print()
    for result in results:
        print_result(result)

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    known_limitation_failures = sum(1 for r in results if not r["passed"] and "known_limitation" in r.get("tags", []))
    summary = f"\n{passed}/{total} passed"
    if known_limitation_failures:
        summary += f" ({known_limitation_failures} of the failures are documented known limitations)"
    print(summary)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS_DIR / f"report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(results, indent=2))
    (RESULTS_DIR / "latest.json").write_text(json.dumps(results, indent=2))
    print(f"Full report written to {report_path.relative_to(TESTING_DIR.parent)}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
