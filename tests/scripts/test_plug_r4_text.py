"""Plug round 4's Spark prompts and reply checks on a hand-written lesson."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
SCRIPT_DIRS = {ROUTEA, ROUTEA.parent / "aidev"}


@pytest.fixture(autouse=True)
def forget_script_modules():
    """Drop only modules loaded from scripts/; shared libraries stay loaded."""
    yield
    for name, module in list(sys.modules.items()):
        if Path(getattr(module, "__file__", None) or "/").parent in SCRIPT_DIRS:
            del sys.modules[name]


@pytest.fixture
def text(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("plug_r4_text", ROUTEA / "plug_r4_text.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plug_r4_text"] = module
    spec.loader.exec_module(module)
    return module


def lesson(text):
    return text.Lesson(
        lesson_id="x1",
        repo="org/r",
        program="pytest",
        file="tests/test_a.py",
        failed="pytest tests/test_a.py",
        error="ImportError: no module named a",
        error_class="ImportError",
        fix="pytest tests/test_a.py -p no:cacheprovider",
        added=("-p", "no:cacheprovider"),
    )


GOOD = (
    "Applies when pytest cannot import the package under test: run "
    "`pytest tests/test_a.py -p no:cacheprovider` instead of `pytest tests/test_a.py`."
)


def test_prompts_carry_only_the_template_text(text):
    found = lesson(text)
    assert found.text() in text.rewrite_prompt(found)
    assert found.text() in text.invent_prompt(found, 5)


def test_a_rewrite_keeping_both_commands_passes(text):
    assert text.checked_rewrite(lesson(text), GOOD) == GOOD


@pytest.mark.parametrize(
    "reply",
    [
        GOOD.replace("-p no:cacheprovider", "-q"),
        GOOD.replace("Applies when", "Use this when"),
        GOOD + "\nAlso clear the cache.",
    ],
)
def test_a_rewrite_that_changes_the_lesson_is_rejected(text, reply):
    with pytest.raises(text.RewriteRejectedError):
        text.checked_rewrite(lesson(text), reply)


def test_situations_quoting_the_fix_are_dropped_and_counted(text):
    reply = (
        'Sure: ["Ran pytest tests/test_b.py, ImportError on module b", '
        '"pytest tests/test_a.py -p no:cacheprovider then ImportError", ""]'
    )
    found = text.parsed_situations(lesson(text), reply)
    assert found.situations == ("Ran pytest tests/test_b.py, ImportError on module b",)
    assert found.dropped == 2


@pytest.mark.parametrize("reply", ["no array here", '["a", 3]', "[not json]"])
def test_a_reply_that_is_not_an_array_of_strings_raises(text, reply):
    with pytest.raises(text.SituationsRejectedError):
        text.parsed_situations(lesson(text), reply)
