import pytest

from symbiont.miner.incident_corrections import situation_of
from symbiont.records.schema import Kind, Provenance, Record


def _run(command):
    return Record(
        harness="h", project="p", session_id="s", step=1, kind=Kind.COMMAND, raw="x",
        provenance=Provenance("t", "x", True), command=command, exit_code=0,
    )  # fmt: skip


@pytest.mark.parametrize(
    "command", ["git -C /repo push", "git -c core.x=1 push origin", "git push"]
)
def test_a_flag_value_is_not_the_step(command):
    assert situation_of(_run(command), frozenset())[:2] == ("before", "git push")
