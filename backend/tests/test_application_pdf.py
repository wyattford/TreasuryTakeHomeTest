import io
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from app.application_pdf import ApplicationPdfError, extract_application_pdf_fields

REFERENCE_PDF = Path(__file__).resolve().parents[2] / "ReferenceDocs" / "f510031.pdf"


def _filled_reference_pdf(field_values: dict[str, str]) -> bytes:
    reader = PdfReader(REFERENCE_PDF)
    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, field_values, auto_regenerate=False)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_extracts_mapped_fields_from_filled_form():
    pdf_bytes = _filled_reference_pdf(
        {
            "6. BRAND NAME (Required)": "OLD TOM DISTILLERY",
            "7. FANCIFUL NAME (If any)": "Reserve Blend",
            "8. NAME AND ADDRESS OF APPLICANT AS SHOWN ON PLANT REGISTRY, BASIC": "123 Main St, Springfield, IL",
            "11.  WINE APPELLATION (If on label)": "Napa Valley",
            "Check Box22": "/Spirits",
            "Check Box34": "/Import",
        }
    )

    fields = extract_application_pdf_fields(pdf_bytes)

    assert fields == {
        "brand_name": "OLD TOM DISTILLERY",
        "fanciful_name": "Reserve Blend",
        "name_address": "123 Main St, Springfield, IL",
        "appellation": "Napa Valley",
        "beverage_class": "distilled_spirits",
        "imported": True,
    }


def test_domestic_wine_checkboxes_map_correctly():
    pdf_bytes = _filled_reference_pdf(
        {
            "6. BRAND NAME (Required)": "SUNNY ACRES WINERY",
            "Check Box22": "/Wine",
            "Check Box34": "/Domes",
        }
    )

    fields = extract_application_pdf_fields(pdf_bytes)

    assert fields["beverage_class"] == "wine"
    assert fields["imported"] is False


def test_unfilled_form_yields_no_fields_but_no_error():
    pdf_bytes = REFERENCE_PDF.read_bytes()

    fields = extract_application_pdf_fields(pdf_bytes)

    assert fields == {}


def test_pdf_without_form_fields_raises():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)

    with pytest.raises(ApplicationPdfError):
        extract_application_pdf_fields(buffer.getvalue())


def test_garbage_bytes_raise_application_pdf_error():
    with pytest.raises(ApplicationPdfError):
        extract_application_pdf_fields(b"not a pdf")
