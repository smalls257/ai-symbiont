"""Customer statements: what a customer owes, grouped by how late it is."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

CURRENT = "current"
OVERDUE = "90+"
# (label, last day past due in the bucket): the usual 30/60/90 aging report.
AGING_BUCKETS = (("1-30", 30), ("31-60", 60), ("61-90", 90))
REPORT_ORDER = (CURRENT, *(label for label, _ in AGING_BUCKETS), OVERDUE)


@dataclass(frozen=True)
class OpenInvoice:
    """An invoice with an unpaid balance."""

    number: str
    due: date
    balance: Decimal


def days_past_due(invoice: OpenInvoice, as_of: date) -> int:
    """Whole days the invoice is late on `as_of`; 0 if not yet due."""
    return max((as_of - invoice.due).days, 0)


def aging_label(days: int) -> str:
    """The aging bucket for an invoice that is `days` late."""
    if days == 0:
        return CURRENT
    for label, last_day in AGING_BUCKETS:
        if days < last_day:
            return label
    return OVERDUE


def aging_report(invoices: list[OpenInvoice], as_of: date) -> dict[str, Decimal]:
    """Total open balance per aging bucket, every bucket present, in report order."""
    totals = dict.fromkeys(REPORT_ORDER, Decimal(0))
    for invoice in invoices:
        totals[aging_label(days_past_due(invoice, as_of))] += invoice.balance
    return totals
