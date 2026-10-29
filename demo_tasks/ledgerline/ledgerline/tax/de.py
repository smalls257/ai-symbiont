"""Germany: standard rate 19 percent, rounded per invoice line."""

from decimal import Decimal

from ledgerline.tax.vat import VatRule


class GermanVat(VatRule):
    """German standard-rate VAT."""

    rate = Decimal("0.19")
