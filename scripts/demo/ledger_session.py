"""A hand-written Claude Code session of the synthetic ledger, for the keyless demo.

Everything here is invented: no real transcript and no model output. It is shaped like a real
session (JSONL events, tool calls answered by tool results) so `symbiont repo mine` reads it with
the same reader it uses on a developer's own history. The failing pytest command that a
later edit fixes is the lesson the recall step in the demo repeats.
"""

import json
import re
from pathlib import Path

FAILING_TEST = "pytest -q -k refund"
# The tail of what `pytest -q -k refund` really prints on examples/ledger (its last failure; the
# miner keeps only the last 240 characters of a quote, so the assertion must sit near the end).
# The same last assertion makes the recall fire when a judge's live Muse session runs that command.
FAILURE_TEXT = (
    "E       AssertionError: ledger/refunds.py: acme balance after a full JPY refund is "
    "-150 USD cents, expected 0\n"
    "E       assert -150 == 0\n"
    "FAILED tests/test_refunds.py::test_full_refund_reverses_the_charge_at_the_stored_rate\n"
    "3 failed, 3 deselected in 0.02s"
)
CORRECTIONS = (
    "every ledger entry gets an audit.record call",
    "convert a fee at today's rate, not the stored rate",
)
SESSION_ID = "demo-ledger-1"
MONEY_FIX = "def to_minor(amount, currency):\n    return int(Decimal(amount))\n"


def _event(role: str, content) -> dict:
    """One session event in Claude Code's shape."""
    return {"type": role, "sessionId": SESSION_ID, "message": {"role": role, "content": content}}


def _say(role: str, text: str) -> dict:
    """A plain conversation turn."""
    return _event(role, text if role == "user" else [{"type": "text", "text": text}])


def _call(ident: str, tool: str, arguments: dict) -> dict:
    """The agent calls a tool."""
    block = {"type": "tool_use", "id": ident, "name": tool, "input": arguments}
    return _event("assistant", [block])


def _result(ident: str, text: str, *, error: bool = False) -> dict:
    """The tool answers."""
    block = {"type": "tool_result", "tool_use_id": ident, "content": text, "is_error": error}
    return _event("user", [block])


def _edit(ident: str, path: str, old: str, new: str) -> list[dict]:
    """An edit and its success."""
    arguments = {"file_path": path, "old_string": old, "new_string": new}
    return [_call(ident, "Edit", arguments), _result(ident, "The file has been updated.")]


def session_events() -> list[dict]:
    """The session: a failing test later fixed, a reworked file, two user corrections."""
    failing = [_call("t1", "Bash", {"command": FAILING_TEST})]
    failing.append(_result("t1", "Exit code 1\n" + FAILURE_TEXT, error=True))
    passing = [_call("t2", "Bash", {"command": FAILING_TEST}), _result("t2", "1 passed")]
    return [
        _say("user", "refunds in yen come out wrong, please fix them"),
        *failing,
        *_edit("e1", "ledger/refunds.py", "to_minor(amount)", "to_minor(amount, 'JPY')"),
        *_edit("e2", "ledger/refunds.py", "to_minor(amount, 'JPY')", "to_minor(amount, cur)"),
        _say("user", CORRECTIONS[0]),
        *_edit("e3", "ledger/money.py", "int(amount)", MONEY_FIX),
        *_edit("e4", "ledger/refunds.py", "to_minor(amount, cur)", "to_minor(amount, c.currency)"),
        *passing,
        _say("user", CORRECTIONS[1]),
    ]


def install_session(home: Path, repo: Path) -> Path:
    """Write the session where Claude Code keeps a repository's logs under `home`."""
    folder_name = re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))
    folder = home / ".claude" / "projects" / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / f"{SESSION_ID}.jsonl"
    log.write_text("\n".join(json.dumps(event) for event in session_events()) + "\n")
    return log
