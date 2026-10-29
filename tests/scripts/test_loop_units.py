"""The recursive loop's pure units: cards, verify, lesson utility, training plan, ledger."""

import importlib
import sys
from pathlib import Path

import pytest

LOOP = Path(__file__).resolve().parents[2] / "scripts" / "loop"


@pytest.fixture(autouse=True)
def loop_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(LOOP))
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def mod(name):
    return importlib.import_module(name)


def card(resolution=None, how="", lesson_id="habit-x", kind="habit"):
    cards = mod("loop_cards")
    return cards.LessonCard(
        lesson_id, "fake", kind, "You found the file.", "The run never edited.",
        "Edit once found.", ("t1",), 0, resolution, how,
    )  # fmt: skip


# -- cards ----------------------------------------------------------------------------------------


def test_a_resolution_needs_proof_and_proof_needs_a_resolution():
    cards = mod("loop_cards")
    with pytest.raises(cards.UnverifiedResolutionError):
        card(how="It was fixed somehow.")
    proof = cards.Resolution(cards.ResolutionSource.OWN_VERIFIED_SUCCESS, ("r0/a",))
    with pytest.raises(cards.UnverifiedResolutionError):
        card(resolution=proof)
    with pytest.raises(cards.UnverifiedResolutionError):
        cards.Resolution(cards.ResolutionSource.UPSTREAM_FIX, ())


def test_an_open_card_teaches_the_mistake_and_the_check_only_and_round_trips():
    cards = mod("loop_cards")
    open_card = card()
    assert open_card.is_open and "How it was resolved" not in open_card.text()
    assert open_card.text().startswith("What happened:")
    proof = cards.Resolution(cards.ResolutionSource.OWN_VERIFIED_SUCCESS, ("r1/a",))
    closed = open_card.resolved_by(proof, "An early edit solved it.")
    assert "How it was resolved: An early edit solved it." in closed.text()
    assert cards.LessonCard.from_json(closed.to_json()) == closed


def test_card_rows_put_the_card_first_and_skip_what_worked_for_an_open_card():
    rows = mod("card_rows").card_rows(card(), "system", "In sqlglot")
    assert [row.kind for row in rows] == ["card", "check"]
    assert rows[0].messages[2]["content"].startswith("What happened:")


# -- verify ---------------------------------------------------------------------------------------


def attempt(task, outcome, split="training", trained=frozenset(), round_index=0):
    at = mod("attempts")
    return at.Attempt(
        f"r{round_index}/{task}", task, round_index, "m", at.Split(split), at.Outcome(outcome),
        trained,
    )  # fmt: skip


def test_verify_keeps_graded_outcomes_and_counts_ungraded_apart():
    at = mod("attempts")
    batch = at.verified([attempt("a", "passed"), attempt("b", "failed"), attempt("c", "passed"),
                         attempt("d", "ungraded")])  # fmt: skip
    assert batch.ungraded == 1 and len(batch.graded) == 3 and len(batch.passed) == 2


def test_a_mostly_ungraded_round_is_an_outage_not_a_round():
    at = mod("attempts")
    with pytest.raises(at.UnverifiableRoundError):
        at.verified([attempt("a", "ungraded"), attempt("b", "ungraded"), attempt("c", "passed")])


def test_held_out_attempts_never_reach_mining():
    at = mod("attempts")
    with pytest.raises(at.HeldOutMiningError):
        at.training_only([attempt("h1", "passed", split="held_out")], frozenset())
    with pytest.raises(at.HeldOutMiningError):
        at.training_only([attempt("h1", "passed")], frozenset({"h1"}))


# -- utility --------------------------------------------------------------------------------------


def baseline_tasks(count, start=0):
    ut = mod("utility")
    found, number = [], start
    while len(found) < count:
        if ut.in_baseline(f"task{number}"):
            found.append(f"task{number}")
        number += 1
    return found


def exposures(lesson_id, trained, rows):
    """rows: (mark, passed) per baseline task."""
    ut = mod("utility")
    tasks = baseline_tasks(len(rows), start=0 if trained else 1000)
    return [
        ut.Exposure(lesson_id, f"{trained}/{t}", t, ut.Mark(mark), passed, trained)
        for t, (mark, passed) in zip(tasks, rows, strict=True)
    ]


HELPS_BEFORE = [("repeated", False)] * 3 + [("avoided", False)] + [("not applicable", True)] * 4
HELPS_AFTER = [("avoided", True)] * 4 + [("not applicable", True)] * 4


def test_a_lesson_that_cut_its_mistake_is_kept_and_one_that_raised_it_is_dropped():
    ut = mod("utility")
    helps = exposures("good", False, HELPS_BEFORE) + exposures("good", True, HELPS_AFTER)
    hurts = exposures("bad", False, HELPS_AFTER) + exposures("bad", True, HELPS_BEFORE)
    table = ut.judge_lessons(
        [ut.LessonRecord("good", "habit", 1), ut.LessonRecord("bad", "habit", 1)], helps + hurts
    )
    assert [(row.decision, row.estimator) for row in table] == [
        (ut.Decision.KEEP, ut.Estimator.OBSERVATIONAL),
        (ut.Decision.DROP, ut.Estimator.OBSERVATIONAL),
    ]
    assert table[0].repeat_before == 0.75 and table[0].repeat_after == 0.0


def test_an_unjudged_lesson_is_on_probation_then_down_weighted():
    ut = mod("utility")
    assert ut.decide(None, 0) is ut.Decision.PROBATION
    assert ut.decide(0.0, ut.PROBATION_ROUNDS) is ut.Decision.DOWN_WEIGHT


def test_enough_ablation_pairs_override_the_observational_score():
    ut = mod("utility")
    helps = exposures("x", False, HELPS_BEFORE) + exposures("x", True, HELPS_AFTER)
    pairs = [ut.AblationPair("x", f"t{i}", False, True) for i in range(ut.MIN_ABLATION_PAIRS)]
    row = ut.judge_lessons([ut.LessonRecord("x", "habit", 1)], helps, pairs)[0]
    assert row.estimator is ut.Estimator.ABLATION and row.decision is ut.Decision.DROP


def test_only_the_never_mined_baseline_half_is_judged():
    ut = mod("utility")
    mined = [t for t in (f"task{i}" for i in range(200)) if not ut.in_baseline(t)][:8]
    rows = [ut.Exposure("x", t, t, ut.Mark.REPEATED, False, False) for t in mined]
    row = ut.judge_lessons([ut.LessonRecord("x", "habit", 0)], rows)[0]
    assert row.applied_untrained == 0 and row.estimator is ut.Estimator.NONE


def test_harvest_quotas_follow_each_kinds_judged_utility():
    ut = mod("utility")
    quotas = ut.harvest_quotas({"habit": 0.4, "repo": -0.3}, ["habit", "repo", "new"], base=6)
    assert quotas == {"habit": 9, "new": 6, "repo": 3}


# -- training plan --------------------------------------------------------------------------------


def row(lesson_id, kind="card", text="x"):
    return mod("training_plan").Row(lesson_id, kind, ({"role": "user", "content": text},))


def plan_inputs(decisions, max_chars=100):
    tp = mod("training_plan")
    rows = {k: [row(k, "card", f"{k} card"), row(k, "check", f"{k} check")] for k in decisions}
    rows["long"] = [row("long", "card", "y" * 500)]
    success = [row("success:a", "success", "did it")]
    return tp.PlanInputs(1, decisions, rows, success, max_chars)


def test_weights_follow_decisions_and_long_rows_are_dropped_and_counted():
    tp, ut = mod("training_plan"), mod("utility")
    decisions = {"keep": ut.Decision.KEEP, "half": ut.Decision.DOWN_WEIGHT,
                 "gone": ut.Decision.DROP, "long": ut.Decision.KEEP}  # fmt: skip
    plan = tp.plan_training(plan_inputs(decisions), tp.TrainMode.FROM_SCRATCH, None)
    assert sorted((r.lesson_id, r.kind) for r in plan.rows) == [
        ("half", "card"), ("keep", "card"), ("keep", "check"), ("success:a", "success"),
    ]  # fmt: skip
    assert plan.start_from is None and plan.manifest["rows_dropped_too_long"] == 1
    assert plan.manifest["lessons_by_decision"]["drop"] == ["gone"]


def test_continued_mode_trains_new_rows_plus_replay_and_names_what_it_cannot_unlearn():
    tp, ut = mod("training_plan"), mod("utility")
    decisions = {"keep": ut.Decision.KEEP, "gone": ut.Decision.DROP}
    old = [row("keep", "card", "keep card"), row("keep", "check", "keep check")]
    previous = tp.PreviousTraining(
        "/host/adapters/r1", frozenset({"keep", "gone"}), frozenset(tp.row_key(r) for r in old)
    )
    plan = tp.plan_training(plan_inputs(decisions), tp.TrainMode.CONTINUED_WITH_REPLAY, previous)
    assert plan.start_from == "/host/adapters/r1"
    assert [r.lesson_id for r in plan.rows].count("success:a") == 1
    assert len(plan.rows) == 1 + round(2 * tp.REPLAY_SHARE)
    assert plan.manifest["dropped_but_in_weights"] == ["gone"]


# -- ledger ---------------------------------------------------------------------------------------


def test_the_held_out_set_is_fixed_at_declaration_and_state_round_trips(tmp_path):
    lg = mod("ledger")
    ledger = lg.Ledger.declare("fake", frozenset({"h1", "h2"}), "route-b", "plain")
    ledger.require_held_out(frozenset({"h2", "h1"}))
    with pytest.raises(lg.HeldOutChangedError):
        ledger.require_held_out(frozenset({"h1"}))
    ledger.cards["habit-x"] = card()
    ledger.attempts.append(attempt("a", "passed"))
    ledger.record_exposure("habit-x", ledger.attempts[0], mod("utility").Mark.AVOIDED)
    path = lg.save(tmp_path, ledger)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    again = lg.load(tmp_path, ledger.key)
    assert again.cards == ledger.cards and again.exposures == ledger.exposures


def test_learning_speed_counts_rounds_and_lessons_until_the_start_is_beaten():
    lg = mod("ledger")
    ledger = lg.Ledger.declare("fake", frozenset({"h1"}), "route-b", "plain")
    for index, passed in enumerate((10, 11, 14)):
        ledger.rounds.append({
            "round": index, "trained_lessons": ["a"] * (index + 2),
            "eval": {"plain_passed": 10, "plain_graded": 20, "start_passed": 10,
                     "start_graded": 20, "adapter_passed": passed, "adapter_graded": 20},
        })  # fmt: skip
    speed = lg.learning_speed(ledger, "start")
    assert speed["rounds_to_improve"] == 3 and speed["lessons_to_improve"] == 4
