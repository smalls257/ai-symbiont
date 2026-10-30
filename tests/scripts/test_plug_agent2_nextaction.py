"""PLUG-AGENT-2 next-action matcher and request history: frozen before any sampling."""

import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
sys.path.insert(0, str(ROUTEA))

from plug_agent2_nextaction import first_command, same_invocation, wire_history  # noqa: E402


def test_the_same_invocation_survives_path_and_spacing_changes():
    assert same_invocation("python  /tmp/abc123/repro.py", "python /tmp/xyz789/repro.py")
    assert same_invocation("pytest tests/a.py -x", "pytest   tests/a.py -x")


def test_a_different_command_or_an_empty_one_is_not_a_repeat():
    assert not same_invocation("pip install sqlglot", "python /tmp/r.py")
    assert not same_invocation("", "")
    assert not same_invocation("", "python r.py")


def test_only_the_head_of_a_long_command_decides():
    long_a = "cat > /tmp/r.py << 'EOF'\n" + "x = 1\n" * 40
    long_b = "cat > /tmp/r.py << 'EOF'\n" + "x = 1\n" * 40 + "y = 2\n"
    assert same_invocation(long_a, long_b)


def test_history_keeps_wire_fields_and_refuses_non_text_content():
    kept = wire_history(
        [{"role": "user", "content": "t", "extra": {"x": 1}, "reasoning_content": "r"}]
    )
    assert kept == [{"role": "user", "content": "t"}]
    with pytest.raises(TypeError):
        wire_history([{"role": "user", "content": [1, 2]}])


def test_first_command_reads_the_first_tool_call_or_nothing():
    call = {"function": {"arguments": '{"command": "ls -la"}'}}
    assert first_command({"choices": [{"message": {"tool_calls": [call]}}]}) == "ls -la"
    assert first_command({"choices": [{"message": {"content": "hi"}}]}) == ""
