"""Aging buckets of a customer statement."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from ledgerline.statement import OpenInvoice, aging_label, aging_report, days_past_due

AS_OF = date(2024, 6, 30)


def overdue(days, balance="100.00", number="INV-1"):
    """An invoice that is `days` late on AS_OF."""
    return OpenInvoice(number, AS_OF - timedelta(days=days), Decimal(balance))


def test_days_past_due_is_zero_before_the_due_date():
    """An invoice not yet due is not late."""
    assert days_past_due(OpenInvoice("INV-2", AS_OF + timedelta(days=5), Decimal(1)), AS_OF) == 0


@pytest.mark.parametrize(
    ("days", "label"), [(0, "current"), (15, "1-30"), (45, "31-60"), (75, "61-90"), (120, "90+")]
)
def test_aging_label_mid_bucket(days, label):
    """Invoices well inside a bucket land in it."""
    assert aging_label(days) == label


def test_aging_report_lists_every_bucket_and_sums_balances():
    """Every bucket is present and balances add up per bucket."""
    report = aging_report([overdue(10, "40.00"), overdue(12, "2.50"), overdue(200, "9")], AS_OF)
    assert list(report) == ["current", "1-30", "31-60", "61-90", "90+"]
    assert report["1-30"] == Decimal("42.50")
    assert report["90+"] == Decimal("9")
    assert report["current"] == Decimal(0)
