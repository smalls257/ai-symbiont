"""Conversion through the 2024-06 rate snapshot (base USD)."""

from decimal import Decimal

import pytest
from ledgerline.errors import UnknownCurrencyError
from ledgerline.money import Money


def test_base_to_other_currency(rates):
    """100 USD at 0.925 is 92.50 EUR."""
    assert rates.convert(Money(Decimal(100), "USD"), "EUR") == Money(Decimal("92.50"), "EUR")


def test_other_currency_to_base(rates):
    """79 GBP at 0.79 is 100 USD."""
    assert rates.convert(Money(Decimal(79), "GBP"), "USD") == Money(Decimal("100.00"), "USD")


def test_same_currency_is_unchanged(rates):
    """Converting to the same currency only rounds."""
    assert rates.convert(Money(Decimal("5"), "CHF"), "CHF") == Money(Decimal("5.00"), "CHF")


def test_unknown_currency_raises(rates):
    """A code with no rate raises instead of converting at 1."""
    with pytest.raises(UnknownCurrencyError):
        rates.convert(Money(Decimal(1), "USD"), "XYZ")
