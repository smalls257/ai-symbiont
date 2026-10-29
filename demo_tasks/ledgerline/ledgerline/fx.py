"""Currency conversion through a table of rates quoted against one base currency."""

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ledgerline.errors import UnknownCurrencyError
from ledgerline.money import Money


@dataclass(frozen=True)
class RateTable:
    """Units of each currency that one unit of `base` buys."""

    base: str
    per_base: dict[str, Decimal]

    def rate(self, currency: str) -> Decimal:
        """Units of `currency` per one unit of the base; raise UnknownCurrencyError."""
        if currency == self.base:
            return Decimal(1)
        if currency not in self.per_base:
            raise UnknownCurrencyError(currency)
        return self.per_base[currency]

    def convert(self, money: Money, to: str) -> Money:
        """`money` expressed in currency `to`, rounded to the cent."""
        source, target = self.rate(money.currency), self.rate(to)
        if money.currency == self.base:
            amount = money.amount * target
        elif to == self.base:
            amount = money.amount / source
        else:
            amount = money.amount * source / target
        return Money(amount, to).rounded()


def load_rates(snapshot: Path) -> RateTable:
    """Read `rates.toml` from a snapshot directory."""
    table = tomllib.loads((snapshot / "rates.toml").read_text())
    return RateTable(table["base"], {code: Decimal(v) for code, v in table["rates"].items()})
