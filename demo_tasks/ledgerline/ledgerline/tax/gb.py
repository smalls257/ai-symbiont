"""United Kingdom: standard rate 20 percent."""

from decimal import Decimal

from ledgerline.tax.vat import VatRule


class UkVat(VatRule):
    """UK standard-rate VAT."""

    rate = Decimal("0.20")
