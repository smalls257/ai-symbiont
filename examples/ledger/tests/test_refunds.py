from ledger.ledger import Ledger
from ledger.refunds import refund


def make():
    """A ledger with one JPY charge."""
    book = Ledger()
    book.charge("c1", "acme", "5000", "JPY", 0.0067)
    return book


def test_jpy_refund_is_in_whole_yen():
    """Jpy refund is in whole yen."""
    r = refund(make(), "c1", "5000")
    assert r.minor == 5000, (
        f"ledger/money.py: JPY refund recorded as {r.minor}"
        f" minor units, expected 5000 (JPY has no minor unit)"
    )


def test_jpy_charge_is_stored_in_whole_yen():
    """Jpy charge is stored in whole yen."""
    book = make()
    stored = book.charges["c1"].amount_minor
    assert stored == 5000, (
        f"ledger/money.py: JPY charge stored as {stored} minor units, expected 5000"
    )


def test_full_refund_reverses_the_charge_at_the_stored_rate():
    """Full refund reverses the charge at the stored rate."""
    book = make()
    refund(book, "c1", "5000")
    balance = book.balance("acme")
    assert balance == 0, (
        f"ledger/refunds.py: acme balance after a full JPY refund is {balance} USD cents"
        f", expected 0"
    )
