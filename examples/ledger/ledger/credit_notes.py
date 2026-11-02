"""Credit notes."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CreditNote:
    """A credit note in minor units."""

    minor: int
    currency: str


def credit_note(amount, currency):
    """Credit note for an amount given in major units, e.g. '1.250'."""
    return CreditNote(int(Decimal(amount) * 100), currency)
