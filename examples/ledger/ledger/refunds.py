"""Refunds."""

from dataclasses import dataclass

from ledger import rates
from ledger.money import to_minor


@dataclass(frozen=True)
class Refund:
    """A posted refund."""

    minor: int
    currency: str
    base_cents: int


def refund(ledger, charge_id, amount):
    """Refund part or all of a charge."""
    charge = ledger.charges[charge_id]
    minor = to_minor(amount)
    cents = ledger.post_refund(charge.account, minor, rates.current(charge.currency))
    return Refund(minor, charge.currency, -cents)
