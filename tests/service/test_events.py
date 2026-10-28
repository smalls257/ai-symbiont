import json

import pytest

from symbiont.core.slot import Decision
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.service.events import EventLog

SIGNATURE = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_a.py", "ImportError"))

pytestmark = pytest.mark.periphery


def lines(log):
    return [json.loads(line) for line in log.path.read_text().splitlines()]


def test_event_log_line_has_hook_signature_records(tmp_path):
    log = EventLog(tmp_path / "run1", "counters")
    log.append("pre_edit", SIGNATURE, [("s0", 4)], ["a note"])
    (event,) = lines(log)
    assert event["hook"] == "pre_edit" and event["filler"] == "counters"
    assert event["signature"] == ["failed_command", "pytest", "tests/test_a.py", "ImportError"]
    assert event["records"] == [["s0", 4]] and event["notes"] == ["a note"] and event["ts"] > 0


def test_a_quiet_event_has_no_signature_and_lines_accumulate(tmp_path):
    log = EventLog(tmp_path, "mushroom")
    log.append("session_start", None, [], [])
    log.append("pre_edit", None, [], [])
    assert [e["signature"] for e in lines(log)] == [None, None]


def test_a_decision_event_never_carries_the_risk(tmp_path):
    pain = PainPoint(SIGNATURE, "s0", 4, (("s0", 4),))
    log = EventLog(tmp_path, "mushroom")
    log.append_decision("pre_edit", Decision(SIGNATURE, (pain,), (), None, risk=0.7312), [])
    (event,) = lines(log)
    assert "7312" not in log.path.read_text() and event["records"] == [["s0", 4]]
    assert event["evidence"] == 1
