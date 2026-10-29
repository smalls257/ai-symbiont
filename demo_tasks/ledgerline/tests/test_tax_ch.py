"""Swiss VAT: 8.1 percent on the invoice total, rounded to 5 centimes."""

from decimal import Decimal

from ledgerline.tax.ch import SwissVat


def test_swiss_vat_rounds_the_total_to_five_centimes():
    """0.39 x 8.1 percent = 0.0316, which rounds to 0.05."""
    assert SwissVat().tax_for([Decimal("0.13")] * 3) == Decimal("0.05")


def test_swiss_vat_on_a_round_amount():
    """1000 x 8.1 percent is exactly 81."""
    assert SwissVat().tax_for([Decimal("400"), Decimal("600")]) == Decimal("81.00")
