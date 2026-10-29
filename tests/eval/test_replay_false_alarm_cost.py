"""Replay teaches every learner the false-alarm cost the context carries."""

from record_builders import say, session
from symbiont.core.slot import Outcome
from symbiont.eval.offline import ReplayContext, Start, replay


class OutcomeSpy:
    name = "spy"

    def __init__(self):
        self.costs = []

    def initial_state(self, seed):
        return None

    def decide(self, x, situation, state):
        from symbiont.core.slot import Decision

        return Decision(None, (), (), "spy", risk=0.0)

    def learn(self, x, outcome: Outcome, state):
        self.costs.append(outcome.false_alarm_cost)
        return state


def one_session():
    from dataclasses import replace

    return [replace(r, task_id="t0") for r in session(say("a"), say("b"), say("c"))]


def test_outcomes_carry_the_cost_in_the_context():
    spy = OutcomeSpy()
    ctx = ReplayContext({}, frozenset(), false_alarm_cost=0.5)
    replay(spy, [one_session()], Start.fresh(), ctx=ctx, seed=0)
    assert spy.costs == [0.5, 0.5, 0.5]


def test_the_default_is_the_balanced_cost_g6_used():
    spy = OutcomeSpy()
    replay(spy, [one_session()], Start.fresh(), ctx=ReplayContext({}, frozenset()), seed=0)
    assert set(spy.costs) == {1.0}
