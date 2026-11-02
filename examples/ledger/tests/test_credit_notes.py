from ledger.credit_notes import credit_note


def test_bhd_credit_note_keeps_the_fils():
    """Bhd credit note keeps the fils."""
    note = credit_note("1.250", "BHD")
    assert note.minor == 1250, (
        f"ledger/credit_notes.py: BHD credit note for 1.250 is {note.minor}"
        f" minor units, expected 1250"
    )
