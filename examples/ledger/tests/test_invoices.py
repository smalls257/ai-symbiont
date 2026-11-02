from ledger.invoices import invoice_total


def test_jpy_invoice_total_is_in_whole_yen():
    """Jpy invoice total is in whole yen."""
    total = invoice_total([("1500", 2), ("2000", 1)], "JPY")
    assert total == 5000, (
        f"ledger/invoices.py: JPY invoice total is {total} minor units, expected 5000"
    )
