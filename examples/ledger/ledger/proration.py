"""Prorated refunds for canceled subscriptions."""

from decimal import ROUND_HALF_UP, Decimal


def prorated_minor(paid, days_left, days_in_period, currency):
    """Minor units to give back for the unused days; `paid` is in major units, e.g. '12.347'."""
    part = (Decimal(paid) * days_left / days_in_period).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return int(part * 100)
