"""The ledger: charges with their stored rate, and USD-cent entries."""

from dataclasses import dataclass

from ledger.money import convert_minor, to_minor


@dataclass(frozen=True)
class Charge:
    """A charge with the rate stored at the time."""

    id: str
    account: str
    currency: str
    amount_minor: int
    rate: float


class Ledger:
    """Charges by id and USD-cent entries."""

    def __init__(self):
        self.charges = {}
        self.entries = []

    def charge(self, charge_id, account, amount, currency, rate):
        """Record a charge and its USD-cent entry."""
        minor = to_minor(amount)
        self.charges[charge_id] = Charge(charge_id, account, currency, minor, rate)
        self.entries.append((account, convert_minor(minor, rate)))

    def post_refund(self, account, minor, rate):
        """Post a refund entry; returns the USD cents."""
        cents = convert_minor(minor, rate)
        self.entries.append((account, -cents))
        return cents

    def balance(self, account):
        """The account's balance in USD cents."""
        return sum(cents for who, cents in self.entries if who == account)
