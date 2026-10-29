"""Switzerland: standard rate 8.1 percent on the invoice total, rounded to 5 centimes."""

from decimal import Decimal

from ledgerline.tax.vat import Rounding, VatRule


class SwissVat(VatRule):
    """Swiss standard-rate VAT."""

    rate = Decimal("0.081")
    rounding = Rounding.PER_INVOICE
    step = Decimal("0.05")
