"""QG-RD-04 comment policy: each rule is shown firing on a planted comment and staying quiet on
a comment that carries a reason."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATES = REPO / "scripts" / "gates"
sys.path.insert(0, str(GATES))

import check_comments  # noqa: E402


def test_a_todo_needs_an_owner_and_a_date():
    bad = check_comments.problems_in("# TODO fix this\nx = 1\n", "a.py")
    good = check_comments.problems_in("# TODO(jane, 2026-11-30): drop after v2\nx = 1\n", "a.py")
    assert len(bad) == 1 and "owner" in bad[0] and good == []


def test_a_comment_that_restates_the_next_line_is_flagged():
    source = "# set the user name from request\nuser_name = request.name\n"
    assert any("restates" in p for p in check_comments.problems_in(source, "a.py"))


def test_a_comment_that_gives_a_reason_is_not_flagged():
    reason = "# because the user name must come from the request, never the session"
    source = f"{reason}\nuser_name = request.name\n"
    assert check_comments.problems_in(source, "a.py") == []


def test_tool_directives_and_inline_comments_are_not_flagged():
    source = "user_name = request.name  # set the user name from request\nx = f()  # noqa: E501\n"
    assert check_comments.problems_in(source, "a.py") == []


def test_a_docstring_that_only_restates_the_signature_is_flagged():
    source = 'def get_total(items):\n    """Returns the total."""\n    return 1\n'
    assert any("restates its signature" in p for p in check_comments.problems_in(source, "a.py"))


def test_a_docstring_that_states_why_or_what_it_raises_passes():
    doc = '"""Prices include tax; raises ValueError on a negative count."""'
    source = f"def total(items):\n    {doc}\n    return 1\n"
    assert check_comments.problems_in(source, "a.py") == []


def run_gate(*files: str) -> int:
    script = str(GATES / "check_comments.py")
    return subprocess.run(
        [sys.executable, script, *files], capture_output=True, text=True
    ).returncode


def test_exit_codes_distinguish_findings_from_a_gate_that_cannot_run(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("# TODO later\nx = 1\n")
    assert run_gate(str(bad)) == 1
    assert run_gate(str(tmp_path / "absent.py")) == 2
    assert run_gate() == 2


def test_framework_vocabulary_in_a_docstring_or_comment_is_refused():
    doc = 'def f():\n    """Violation prevented: **Distributed Monolith** here."""\n'
    comment = "# this avoids a Silent Fallback\nx = 1\n"
    label = "# Sensor -> restore timing\nx = 1\n"
    for source in (doc, comment, label):
        assert any("framework term" in p for p in check_comments.problems_in(source, "a.py")), (
            source
        )


def test_ordinary_use_of_a_principle_word_is_not_vocabulary():
    source = '"""Filter rows by id; the engine of the sensor loop buffers input."""\n'
    assert not any("framework" in p for p in check_comments.problems_in(source, "a.py"))


def test_docstring_caps_are_three_five_and_six_lines():
    def doc(lines: int) -> str:
        return "\n".join(f"line {n}" for n in range(lines))

    def over(source: str) -> bool:
        return any("docstring over" in p for p in check_comments.problems_in(source, "a.py"))

    func = 'def f():\n    """{}"""\n'
    klass = 'class C:\n    """{}"""\n'
    assert over(func.format(doc(4))) and not over(func.format(doc(3)))
    assert over(klass.format(doc(6))) and not over(klass.format(doc(5)))
    assert over(f'"""{doc(7)}"""\n') and not over(f'"""{doc(6)}\nUsage: x FILE"""\n')


def test_a_comment_block_over_three_lines_is_refused():
    four = "# why one\n# why two\n# why three\n# why four\nx = 1\n"
    three = "# why one\n# why two\n# why three\nx = 1\n"
    assert any("comment block" in p for p in check_comments.problems_in(four, "a.py"))
    assert not any("comment block" in p for p in check_comments.problems_in(three, "a.py"))
