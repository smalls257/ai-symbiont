"""Soak tests: random ledgers for a fixed time budget, checking invariants that must never break."""

import random
import time
from datetime import date, timedelta
from decimal import Decimal

from ledgerline.money import Money, format_amount, parse_amount
from ledgerline.statement import REPORT_ORDER, OpenInvoice, aging_label, aging_report

# Each soak test keeps generating random input this long; the budget is the point of a soak test.
SOAK_SECONDS = 25
AS_OF = date(2024, 6, 30)


def random_invoices(rng):
    """A random statement of up to 50 open invoices."""
    return [
        OpenInvoice(
            f"INV-{n}",
            AS_OF - timedelta(days=rng.randint(-30, 400)),
            Decimal(rng.randint(1, 10**7)) / 100,
        )
        for n in range(rng.randint(0, 50))
    ]


def soak(check):
    """Run `check(rng)` with fresh random input until the time budget is spent."""
    rng = random.Random(20240630)
    deadline = time.monotonic() + SOAK_SECONDS
    rounds = 0
    while time.monotonic() < deadline:
        check(rng)
        rounds += 1
    assert rounds > 0


def test_aging_report_keeps_every_cent():
    """The buckets always add up to the total open balance."""

    def check(rng):
        invoices = random_invoices(rng)
        report = aging_report(invoices, AS_OF)
        assert sum(report.values()) == sum((inv.balance for inv in invoices), Decimal(0))

    soak(check)


def test_aging_labels_are_known_buckets():
    """Every lateness maps to one of the report's buckets."""

    def check(rng):
        assert aging_label(rng.randint(0, 5000)) in REPORT_ORDER

    soak(check)


def test_amounts_survive_format_and_parse():
    """Formatting then parsing an amount gives the amount back."""

    def check(rng):
        money = Money(Decimal(rng.randint(-(10**9), 10**9)) / 100, "USD")
        text = format_amount(money).removesuffix(" USD")
        assert parse_amount(text, "USD") == money

    soak(check)


def test_aging_is_monotonic_in_lateness():
    """A later invoice never lands in an earlier bucket."""

    def check(rng):
        days = rng.randint(0, 5000)
        earlier = REPORT_ORDER.index(aging_label(days))
        assert REPORT_ORDER.index(aging_label(days + rng.randint(0, 40))) >= earlier

    soak(check)
