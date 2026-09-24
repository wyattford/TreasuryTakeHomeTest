import pytest

from app.matching.text_utils import parse_net_contents_ml


@pytest.mark.parametrize(
    ("text", "expected_ml"),
    [
        ("750 mL", 750),
        ("750ML", 750),
        ("75 cl", 750),
        ("1.75 L", 1750),
        ("1 Liter", 1000),
        ("0,75 l", 750),
        ("12 FL OZ", 354.88),
        ("12 fl. oz.", 354.88),
        ("1 PINT 8 FL OZ", 709.76),
        ("750 mL (25.4 FL OZ)", 750),  # metric statement wins, not summed
        ("1 gal", 3785.41),
    ],
)
def test_parses_common_net_contents_statements(text, expected_ml):
    assert parse_net_contents_ml(text) == pytest.approx(expected_ml, abs=0.01)


def test_unparseable_returns_none():
    assert parse_net_contents_ml("one bottle") is None
