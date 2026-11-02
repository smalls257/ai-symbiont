from ledger.proration import prorated_minor


def test_kwd_proration_rounds_at_the_fils():
    """Kwd proration rounds at the fils."""
    refund = prorated_minor("12.347", 1, 3, "KWD")
    assert refund == 4116, (
        f"ledger/proration.py: KWD proration of 12.347 over 1/3 is {refund}"
        f" minor units, expected 4116"
    )
