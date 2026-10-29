"""German VAT: 19 percent, rounded on each line."""

from decimal import Decimal

from ledgerline.tax.de import GermanVat


def test_german_vat_on_one_line():
    """One line: 19 percent rounded half up."""
    assert GermanVat().tax_for([Decimal("100.00")]) == Decimal("19.00")


def test_german_vat_rounds_each_line():
    """Three lines of 0.13 are rounded one by one: 3 x 0.02."""
    assert GermanVat().tax_for([Decimal("0.13")] * 3) == Decimal("0.06")
