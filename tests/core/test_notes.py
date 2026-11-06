import json
import re

from record_builders import run
from symbiont.core.notes import NoteKind, render
from symbiont.core.slot import Decision, event_fields
from symbiont.miner.painpoint import PainPoint, Signal, Signature

FAILED = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_tokens.py", "ImportError"))
BLAST = Signature(Signal.BLAST_RADIUS, ("src/parser.py", "src/tokens.py"))
RISK = 0.7312
FORBIDDEN = re.compile(r"score|KC|feature|threshold", re.IGNORECASE)


def pain(signature, step=1):
    return PainPoint(signature, "s0", step, (("s0", step),))


def decision(signature, count=2, recall=()):
    why = tuple(pain(signature, step) for step in range(count))
    return Decision(signature, why, tuple(recall), None, risk=RISK)


def test_note_has_no_numbers_except_counts():
    for signature in (FAILED, BLAST):
        for note in render(decision(signature, count=3)):
            assert not re.search(r"\d+\.\d+", note) and not FORBIDDEN.search(note)
            leftover = re.sub(r"\b\d+ times\b", "", note)
            assert not re.search(r"\d", leftover), note


def test_a_rendered_note_never_carries_the_risk():
    rendered = " ".join(render(decision(FAILED, recall=[run("pytest tests/test_tokens.py")])))
    assert str(RISK) not in rendered and "7312" not in rendered
    assert str(RISK) not in json.dumps(event_fields(decision(FAILED)))


def test_max_two_notes():
    recalled = [run(f"make target{n}") for n in "abc"]
    assert len(render(decision(FAILED, recall=recalled))) == 2
    assert len(render(decision(FAILED, recall=recalled), max_notes=1)) == 1


def test_blast_radius_wording():
    (note,) = render(decision(BLAST, count=1))
    assert "`src/parser.py`" in note and "without touching `src/tokens.py`" in note
    assert "tests" in note and "broke" in note


def test_failed_command_names_the_error_in_words():
    (note,) = render(decision(FAILED, count=1))
    assert (
        note == "This command has failed once before: `pytest tests/test_tokens.py` -> ImportError."
    )


def test_a_quiet_decision_renders_nothing():
    assert render(Decision(None, (), (), "no history for this project yet")) == []


def test_kinds_share_one_budget_and_can_be_chosen():
    recalled = [run("make targeta")]
    both = render(decision(FAILED, recall=recalled))
    assert len(both) == 2 and both[0].startswith("This command has failed")
    only_recall = render(decision(FAILED, recall=recalled), kinds=[NoteKind.RECALL])
    assert only_recall == ["Earlier in this project you ran `make targeta`."]
    assert render(decision(FAILED), kinds=[]) == []


def test_a_rendered_failure_note_never_shows_matching_tokens():
    from record_builders import run
    from symbiont.core.notes import happened
    from symbiont.miner.failure_keys import what_broke
    from symbiont.miner.painpoint import Signal, Signature

    record = run("pytest tests/test_a.py", 1, "E   assert /tmp/x/y.txt == 42")
    broke = what_broke(record, "pytest", inline=False)
    assert "<n>" in broke and "<path>" in broke  # grouping form keeps the tokens
    signature = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_a.py", broke))
    texts = [happened(signature), *render(decision(signature, count=3))]
    assert texts[1:], "the repeat note was rendered"
    for text in texts:
        assert "<n>" not in text and "<path>" not in text
