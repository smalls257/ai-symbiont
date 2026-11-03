import pytest

from symbiont.delivery.headline import MAX_HEADLINE_CHARS, headline

LONG = (
    "[symbiont] In this repo: Never use floats for money amounts in the ledger code, because "
    "rounding drifts and totals stop matching the bank statement after a few thousand rows."
)
CORRECTION = "You were corrected in billing 3 times before, on: keep amounts in integer cents."
REPEAT = (
    "Last time, `pytest tests/test_parser.py` failed with ImportError; it was fixed when you x."
)


def test_a_long_note_becomes_one_short_line_cut_at_a_word():
    line = headline([LONG])
    assert len(line) <= MAX_HEADLINE_CHARS
    assert line.startswith("symbiont · Never use floats for money")
    lead = line.removesuffix(" (this repo's rule)")
    assert lead.endswith("…")
    last_word = lead.removesuffix("…").rsplit(" ", 1)[1]
    assert last_word in LONG.replace(",", "").split()


@pytest.mark.parametrize("stem", ["internationalization", "of", "currency", "x" * 30])
def test_no_headline_ever_ends_mid_word(stem):
    note = " ".join([stem, "of", "currency", "formatting"] * 8)
    words = set(note.split())
    lead = headline([note]).removeprefix("symbiont · ").removesuffix(" (this repo's rule)")
    assert lead.removesuffix("…").rsplit(" ", 1)[-1] in words


def test_a_short_note_is_kept_whole_with_its_provenance():
    assert headline([CORRECTION]) == "symbiont · keep amounts in integer cents (your correction)"


def test_a_repeat_note_is_attributed_to_the_history():
    assert headline([REPEAT]).endswith("(your history)")


def test_two_notes_show_the_first_headline_and_a_count():
    line = headline([LONG, CORRECTION])
    assert line.startswith("symbiont · 2 notes: Never use floats")
    assert line.endswith(("… +1", " +1"))
    assert len(line) <= MAX_HEADLINE_CHARS


def test_no_notes_say_nothing():
    assert headline([]) == ""
