"""UK VAT: 20 percent."""

from decimal import Decimal

from ledgerline.tax.gb import UkVat


def test_uk_vat_on_one_line():
    """One line: 20 percent."""
    assert UkVat().tax_for([Decimal("49.99")]) == Decimal("10.00")


def test_uk_vat_on_no_lines_is_zero():
    """An empty invoice owes no VAT."""
    assert UkVat().tax_for([]) == Decimal(0)
