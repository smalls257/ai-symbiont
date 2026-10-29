"""Recall scoring for the sqlglot adapter smoke, on a hand-written lesson."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "routeb" / "score_sqlglot_recall.py"

LESSON = {
    "lesson_id": "fail-1",
    "happened": "You opened `sqlglot/parser.py` and never edited it.",
    "resolved": "The fix went in `Parser.TYPE_TOKENS` in `sqlglot/parser.py`.",
    "check": "python -m unittest tests.dialects.test_dialect",
    "file": "sqlglot/parser.py",
    "place": "`Parser.TYPE_TOKENS`",
}
QUESTION = {"question_id": "fail-1-q", "lesson_id": "fail-1", "text": "What should I know?"}


@pytest.fixture
def recall():
    spec = importlib.util.spec_from_file_location("score_sqlglot_recall", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["score_sqlglot_recall"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["score_sqlglot_recall"]


def test_a_note_hit_needs_the_place_and_the_file(recall):
    known = recall.vocabulary([LESSON])
    full = recall.verdict("Edit `Parser.TYPE_TOKENS` in `sqlglot/parser.py`.", LESSON, known)
    assert full == {"place": True, "file": True, "check": False, "note": True, "invented": False}
    vague = recall.verdict("Look at the parser's type handling.", LESSON, known)
    assert not vague["note"] and not vague["place"]


def test_a_file_or_place_no_lesson_holds_counts_as_invented(recall):
    known = recall.vocabulary([LESSON])
    made_up = recall.verdict("Edit `Tokenizer.KEYWORDS` in sqlglot/tokens.py.", LESSON, known)
    assert made_up["invented"] and not made_up["note"]


def test_rates_cover_every_question_and_a_missing_answer_raises(recall):
    lessons = {"fail-1": LESSON}
    answers = {"fail-1-q": "Edit Parser.TYPE_TOKENS in sqlglot/parser.py"}
    scored = recall.score_arm(answers, [QUESTION], lessons)
    assert scored["questions"] == 1 and scored["note_rate"] == 1.0
    with pytest.raises(KeyError):
        recall.score_arm({}, [QUESTION], lessons)
