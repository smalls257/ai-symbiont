"""Where a Decision's risk may go. Violation prevented: **Leaky Narrative**.

Risk is an evaluation number; no string, dict or log line built from a
Decision may carry it. Task 15 adds the rendered-note test once a note
renderer exists; until then these guards bite on every path that exists.
"""

import dataclasses
import json
from pathlib import Path

from symbiont.core.slot import Decision, event_fields
from symbiont.miner.painpoint import Signal, Signature

SENTINEL = 0.123456789
SIGNATURE = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_a.py", "ImportError"))
SRC = Path(__file__).resolve().parents[2] / "src" / "symbiont"
# The only source files allowed to read a Decision's risk. A new reader (a note
# renderer, an event log, an exporter) fails this test until someone decides on purpose.
MAY_READ_RISK = {"eval/warning_budget_metrics.py"}


def decision():
    return Decision(SIGNATURE, (), (), None, risk=SENTINEL)


def test_event_fields_carry_what_happened_and_never_the_risk():
    fields = event_fields(decision())
    assert fields["trouble"] == ["failed_command", "pytest", "tests/test_a.py", "ImportError"]
    assert "risk" not in fields and str(SENTINEL) not in json.dumps(fields)


def test_every_string_form_of_a_decision_hides_the_risk():
    d = decision()
    for text in (repr(d), str(d), f"{d}", format(d)):
        assert str(SENTINEL) not in text


def test_the_quiet_decision_event_names_its_reason():
    quiet = Decision(None, (), (), "nothing yet", risk=SENTINEL)
    fields = event_fields(quiet)
    assert fields["trouble"] is None and fields["reason_none"] == "nothing yet"
    assert str(SENTINEL) not in json.dumps(fields)


def test_raw_asdict_is_not_a_sanctioned_serialiser():
    # asdict walks every field, risk included: that is why event_fields exists.
    assert "risk" in dataclasses.asdict(decision())


def test_only_the_allow_listed_files_read_a_decisions_risk():
    sources = sorted(SRC.rglob("*.py"))
    assert len(sources) > 20 and any(p.parts[-2] == "core" for p in sources), "scan found no source"
    readers = {
        str(p.relative_to(SRC)) for p in sources if ".risk" in p.read_text() and p.name != "slot.py"
    }
    assert readers == MAY_READ_RISK


def test_no_source_serialises_a_core_decision_with_asdict():
    users = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if "symbiont.core.slot" in p.read_text() and "asdict(" in p.read_text()
    ]
    assert users == []


def test_the_scan_covers_the_layers_that_will_hold_notes():
    layers = {p.relative_to(SRC).parts[0] for p in SRC.rglob("*.py")}
    assert {"core", "eval", "store"} <= layers
