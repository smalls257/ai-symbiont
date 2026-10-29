"""Parsing and formatting amounts."""

from decimal import Decimal

import pytest
from ledgerline.errors import AmountFormatError
from ledgerline.money import Money, format_amount, parse_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [("12", "12"), ("1,234.50", "1234.50"), ("-7.5", "-7.5"), (" 1000000 ", "1000000")],
    ids=["whole", "grouped", "negative", "padded"],
)
def test_parse_amount_reads_plain_and_grouped_amounts(text, expected):
    """Grouped, signed and padded amounts parse to the same Decimal."""
    assert parse_amount(text, "USD") == Money(Decimal(expected), "USD")


@pytest.mark.parametrize("text", ["", "1,23", "12.345", "abc", "1.2.3"])
def test_parse_amount_refuses_text_that_is_not_an_amount(text):
    """Malformed text raises instead of parsing to something close."""
    with pytest.raises(AmountFormatError):
        parse_amount(text, "USD")


def test_format_amount_groups_and_rounds_half_up():
    """Formatting rounds half up to the cent and groups thousands."""
    assert format_amount(Money(Decimal("-1234.505"), "EUR")) == "-1,234.51 EUR"
