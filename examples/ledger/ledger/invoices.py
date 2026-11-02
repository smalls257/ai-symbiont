"""Invoice totals."""

from decimal import Decimal


def invoice_total(lines, currency):
    """Total in minor units of (unit price in major units, quantity) lines."""
    total = sum(Decimal(price) * quantity for price, quantity in lines)
    return int(total * 100)
