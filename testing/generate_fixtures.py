#!/usr/bin/env python3
"""Builds the test gauntlet's fixtures: renders each case's label image(s)
and computes its expected verdicts.

Expected verdicts are never hand-typed — they come from running the real
production matching engine (`app.matching.engine.compare`) against the
case's ground-truth label content, treated as if it were a perfect
extraction. That keeps the gauntlet honest: if the rules change, regenerating
fixtures picks up the change automatically instead of drifting out of sync
with hand-written expectations.

Usage:
    uv run --project ../backend python generate_fixtures.py
    uv run --project ../backend python generate_fixtures.py --only blur_correct rotate_incorrect
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

TESTING_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTING_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(TESTING_DIR))

from cases import CASES, CaseSpec  # noqa: E402
from distortions import apply_distortion  # noqa: E402
from label_content import TEMPLATES, LabelContent  # noqa: E402
from render import render_back, render_front  # noqa: E402

from app.matching.engine import MATCH, compare  # noqa: E402
from app.schemas import ApplicationIn, ExtractedLabelFields  # noqa: E402

IMAGES_DIR = TESTING_DIR / "fixtures" / "images"
MANIFEST_PATH = TESTING_DIR / "fixtures" / "manifest.json"

# LabelContent field name -> ApplicationIn field name, where they differ.
_LABEL_TO_APPLICATION_FIELD = {"abv_percent": "abv"}
_APPLICATION_FIELDS = (
    "beverage_class",
    "imported",
    "brand_name",
    "fanciful_name",
    "class_type",
    "abv",
    "net_contents",
    "name_address",
    "country_of_origin",
    "appellation",
    "sulfite_declaration",
)


def _declared_base(label: LabelContent) -> dict:
    content = asdict(label)
    declared = {}
    for key, value in content.items():
        mapped_key = _LABEL_TO_APPLICATION_FIELD.get(key, key)
        if mapped_key in _APPLICATION_FIELDS:
            declared[mapped_key] = value
    return declared


def _ground_truth_extraction(label: LabelContent) -> ExtractedLabelFields:
    return ExtractedLabelFields(
        brand_name=label.brand_name,
        fanciful_name=label.fanciful_name,
        class_type=label.class_type,
        abv_percent=label.abv_percent,
        net_contents=label.net_contents,
        name_address=label.name_address,
        country_of_origin=label.country_of_origin,
        appellation=label.appellation,
        sulfite_declaration=label.sulfite_declaration,
        government_warning_text=label.government_warning_text,
        other_disclosures=label.other_disclosures,
        illegible_fields=[],
    )


def build_case(spec: CaseSpec) -> dict:
    label = replace(TEMPLATES[spec.template], **spec.label_overrides)
    declared = {**_declared_base(label), **spec.declared_overrides}
    application = ApplicationIn(**declared)
    ground_truth = _ground_truth_extraction(label)
    verdicts = compare(application, ground_truth)
    overall_status = "clear" if all(v.status == MATCH for v in verdicts) else "flagged"

    front = apply_distortion(render_front(label), spec.distortion)
    back = apply_distortion(render_back(label), spec.distortion)

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    front_path = IMAGES_DIR / f"{spec.id}_front.png"
    back_path = IMAGES_DIR / f"{spec.id}_back.png"
    front.save(front_path)
    back.save(back_path)

    return {
        "id": spec.id,
        "description": spec.description,
        "tags": spec.tags,
        "template": spec.template,
        "distortion": spec.distortion,
        "front_image": str(front_path.relative_to(TESTING_DIR)),
        "back_image": str(back_path.relative_to(TESTING_DIR)),
        "declared": declared,
        "expected": {
            "overall_status": overall_status,
            "fields": [
                {
                    "field_name": v.field_name,
                    "status": v.status,
                    "match_type": v.match_type,
                    "application_value": v.application_value,
                    "extracted_value": v.extracted_value,
                    "detail": v.detail,
                }
                for v in verdicts
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", metavar="CASE_ID", help="Only (re)generate these case ids.")
    args = parser.parse_args()

    ids_filter = set(args.only) if args.only else None
    specs = [c for c in CASES if ids_filter is None or c.id in ids_filter]
    if ids_filter:
        missing = ids_filter - {c.id for c in specs}
        if missing:
            raise SystemExit(f"Unknown case id(s): {sorted(missing)}")

    seen_ids = set()
    for spec in specs:
        if spec.id in seen_ids:
            raise SystemExit(f"Duplicate case id: {spec.id}")
        seen_ids.add(spec.id)

    manifest = [build_case(spec) for spec in specs]

    if ids_filter and MANIFEST_PATH.exists():
        existing = {c["id"]: c for c in json.loads(MANIFEST_PATH.read_text())}
        existing.update({c["id"]: c for c in manifest})
        manifest = list(existing.values())

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    relative_path = MANIFEST_PATH.relative_to(TESTING_DIR.parent)
    print(f"Generated {len(specs)} case(s); manifest now has {len(manifest)} total -> {relative_path}")


if __name__ == "__main__":
    main()
