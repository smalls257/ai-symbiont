"""Shared VAT arithmetic. Country modules subclass VatRule and override what differs."""

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class Rounding(StrEnum):
    """Where VAT is rounded: on each invoice line, or once on the invoice total."""

    PER_LINE = "per_line"
    PER_INVOICE = "per_invoice"


class VatRule:
    """VAT at one rate. Defaults: round each line half up to the cent."""

    rate = Decimal("0")
    rounding = Rounding.PER_LINE
    step = Decimal("0.01")

    def round_tax(self, amount: Decimal) -> Decimal:
        """Round a tax amount half up to this rule's step."""
        return (amount / self.step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * self.step

    def tax_for(self, line_amounts: list[Decimal]) -> Decimal:
        """VAT owed on an invoice with these net line amounts."""
        if self.rounding is Rounding.PER_INVOICE:
            return self.round_tax(sum(line_amounts, Decimal(0)) * self.rate)
        return sum((self.round_tax(line * self.rate) for line in line_amounts), Decimal(0))
