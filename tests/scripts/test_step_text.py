"""The T49 step text keeps the action and the head and tail of the observation."""

import importlib.util
from pathlib import Path

import pytest

from record_builders import _record, edit, run
from symbiont.records.schema import Kind

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "offline" / "step_text.py"
_SPEC = importlib.util.spec_from_file_location("step_text", _PATH)
st = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(st)


def test_a_command_keeps_its_command_and_short_output_whole():
    text = st.step_text(run("pytest -x", exit_code=1, output="E   AssertionError\n[exit 1]"))
    assert text == "$ pytest -x\nE   AssertionError\n[exit 1]"


def test_a_long_observation_keeps_only_its_head_and_tail():
    raw = "H" * 300 + "M" * 5000 + "T" * 300
    cut = st.snippet(raw)
    assert cut.startswith("H" * st.HEAD_CHARS)
    assert cut.endswith("T" * st.TAIL_CHARS)
    assert "M" not in cut
    assert len(cut) == st.HEAD_CHARS + len(st.GAP) + st.TAIL_CHARS


def test_a_long_command_is_cut_to_the_cap():
    text = st.step_text(run("cat <<EOF\n" + "x" * 1000, output=""))
    assert text == "$ " + ("cat <<EOF\n" + "x" * 1000)[: st.ACTION_CHARS]


def test_an_edit_names_its_kind_and_file():
    assert st.step_text(edit("src/app.py")) == "edit src/app.py\nedited"


@pytest.mark.parametrize("kind", [Kind.AGENT_TURN, Kind.USER_TURN])
def test_a_turn_without_files_names_its_kind(kind):
    assert (
        st.step_text(_record(kind, "I will run the tests")) == f"{kind.value}\nI will run the tests"
    )
