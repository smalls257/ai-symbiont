"""Amounts of money: a Decimal plus an ISO 4217 currency code."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ledgerline._amount_grammar import split_amount

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Money:
    """An amount in one currency."""

    amount: Decimal
    currency: str

    def rounded(self) -> "Money":
        """The amount rounded half up to whole cents."""
        return Money(self.amount.quantize(CENT, rounding=ROUND_HALF_UP), self.currency)


def parse_amount(text: str, currency: str) -> Money:
    """Read an amount written like `1,234.50` or `-12`; raise AmountFormatError otherwise."""
    sign, digits = split_amount(text)
    return Money(sign * Decimal(digits), currency)


def format_amount(money: Money) -> str:
    """Write an amount with group separators and two decimals, e.g. `-1,234.50 EUR`."""
    return f"{money.rounded().amount:,.2f} {money.currency}"
