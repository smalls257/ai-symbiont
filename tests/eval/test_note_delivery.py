"""Note delivery: boundary steps, trouble spells, and notes spent online under a budget."""

import numpy as np
import pytest

from record_builders import edit, run, say, session
from symbiont.eval.note_delivery import (
    COOLDOWN_STEPS,
    NO_SPELL,
    DeliveryRule,
    Gate,
    NoteTrace,
    boundary_steps,
    note_steps,
    spell_ids,
)


def test_a_failed_command_and_a_second_edit_of_a_file_are_boundaries():
    steps = session(
        say("start"),
        run("pytest tests/test_x.py", exit_code=1),
        edit("a.py"),
        edit("b.py"),
        edit("a.py"),
        run("pytest tests/test_x.py", exit_code=0),
    )
    assert boundary_steps(steps) == (False, True, False, False, True, False)


def test_an_empty_grep_is_an_answer_not_a_boundary():
    assert boundary_steps(session(run("grep -rn foo src", exit_code=1))) == (False,)


def test_a_rejected_edit_does_not_make_the_next_edit_a_rework():
    steps = session(edit("a.py", exit_code=1), edit("a.py"), edit("a.py"))
    assert boundary_steps(steps) == (False, False, True)


def test_spells_are_numbered_runs_of_steps_followed_by_trouble():
    ids = spell_ids([False, True, True, False, True, False, False, True])
    assert ids.tolist() == [NO_SPELL, 0, 0, NO_SPELL, 1, NO_SPELL, NO_SPELL, 2]
    assert spell_ids([]).tolist() == []


def test_without_budget_or_cooldown_every_qualifying_step_carries_a_note():
    risk = np.array([0.9, 0.1, 0.9, 0.9])
    steps = note_steps(risk, np.ones(4, dtype=bool), 0.5, DeliveryRule(Gate.EVERY_STEP))
    assert steps.tolist() == [0, 2, 3]


def test_the_budget_is_spent_online_on_the_first_qualifying_steps():
    risk = np.array([0.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.99])
    rule = DeliveryRule(Gate.EVERY_STEP, budget=1)
    # the much riskier last step gets nothing: a live harness cannot see the future
    assert note_steps(risk, np.ones(8, dtype=bool), 0.5, rule).tolist() == [0]


def test_no_note_within_the_cooldown_of_the_last_one():
    risk = np.full(12, 0.9)
    rule = DeliveryRule(Gate.EVERY_STEP, budget=3, cooldown=COOLDOWN_STEPS)
    assert note_steps(risk, np.ones(12, dtype=bool), 0.5, rule).tolist() == [0, 6]


def test_the_boundary_gate_only_lets_eligible_steps_speak():
    risk = np.full(4, 0.9)
    eligible = np.array([False, True, False, True])
    rule = DeliveryRule(Gate.BOUNDARY)
    assert note_steps(risk, eligible, 0.5, rule).tolist() == [1, 3]


def test_a_trace_whose_columns_do_not_line_up_is_refused():
    with pytest.raises(ValueError, match="differ in length"):
        NoteTrace("t", (True, False), (0.1,), (False, False))
