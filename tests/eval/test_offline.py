"""Offline replay on synthetic sessions: no repo, no data file, no clock."""

from dataclasses import replace

import pytest

from record_builders import edit, run, say, session, view
from symbiont.core.counters import Counters
from symbiont.core.mushroom import Mushroom
from symbiont.core.similarity import Similarity
from symbiont.eval.offline import (
    History,
    OfflineScores,
    ReplayContext,
    SessionScores,
    Start,
    auroc,
    drop_taskless,
    hub_modules,
    pain_labels,
    replay,
    split_by_task,
)
from symbiont.eval.offline_table import MissingRowError, render_table
from symbiont.eval.offline_verdict import (
    MARGIN,
    bootstrap_auroc_gap,
    bootstrap_auroc_interval,
    fly_default,
    live_learner,
)
from symbiont.miner.mine import mine_session
from symbiont.store.references import build_references


def fresh_ctx():
    return ReplayContext(references={}, hubs=frozenset())


TEST_FILE = "tests/test_tokens.py"
BROKEN = "ImportError: cannot import name 'x'"


def trap_session(sid: str, task: str):
    """The planted trap: the tests file is opened, something is edited, and the
    run of that file fails with the same ImportError, every time."""
    records = session(
        view(TEST_FILE),
        edit("sqlglot/parser.py"),
        run(f"python -m pytest {TEST_FILE} -q", 1, BROKEN),
        *[say("done") for _ in range(7)],
    )
    return [replace(r, session_id=sid, task_id=task) for r in records]


def quiet_session(sid: str, task: str):
    records = session(view("README.md"), edit("README.md"), *[say("ok") for _ in range(8)])
    return [replace(r, session_id=sid, task_id=task) for r in records]


def scored(decider, todo, history=None, *, ctx=None, state=None):
    history = History.empty() if history is None else history
    ctx = ctx or fresh_ctx()
    return replay(decider, todo, Start(history, state), ctx=ctx, seed=0).scores


def test_counters_catch_planted_trap():
    past = [trap_session(f"h{i}", f"t{i}") for i in range(3)]
    history = History.from_sessions(past, fresh_ctx())
    todo = [trap_session(f"n{i}", f"u{i}") for i in range(3)] + [quiet_session("q", "uq")]
    scores = scored(Counters(), todo, history)
    assert scores.decider == "counters"
    assert scores.auroc > 0.6
    first_step_of_trap = scores.per_session[0]
    assert first_step_of_trap.flagged[0], "opening the tests file should warn"
    assert not any(scores.per_session[3].flagged), "the quiet session has nothing to warn about"


def test_nothing_is_known_before_the_first_session_ends():
    todo = [trap_session(f"n{i}", f"u{i}") for i in range(3)]
    scores = scored(Counters(), todo)
    assert not any(scores.per_session[0].flagged)
    assert not any(scores.per_session[1].flagged), "one earlier failure is below min_count"
    assert any(scores.per_session[2].flagged), "online: two finished sessions are now history"


def test_labels_look_only_at_the_next_five_steps():
    todo = [trap_session("n0", "u0")]
    scores = scored(Counters(), todo)
    labels = scores.per_session[0].followed
    assert labels[:2] == (True, True)  # failure at step 2 is within 5 steps of 0 and 1
    assert not any(labels[2:])  # not a warning about itself, nor about the past


def test_similarity_is_scored_on_recall_not_flags():
    past = [trap_session(f"h{i}", f"t{i}") for i in range(3)]
    history = History.from_sessions(past, fresh_ctx())
    todo = [trap_session("n0", "u0")]
    scores = scored(Similarity(), todo, history)
    assert not any(scores.per_session[0].flagged)
    assert scores.recall_at_3 == 1.0


def test_decider_with_no_recall_has_no_recall_score():
    scores = scored(Counters(), [trap_session("n0", "u0")])
    assert scores.recall_at_3 is None


def test_hub_breakage_is_not_a_label():
    refs = {
        "sqlglot/parser.py": frozenset({"sqlglot/tokens.py"}),
        "sqlglot/tokens.py": frozenset({TEST_FILE}),
    }
    s = session(
        edit("sqlglot/parser.py"),
        run(f"pytest {TEST_FILE}", 1, f"FAILED {TEST_FILE}::T::t - KeyError"),
    )
    kinds = lambda hubs: {p.signature.signal.value for p in pain_labels(s, refs, hubs)}  # noqa: E731
    assert "blast_radius" in kinds(frozenset())
    assert "blast_radius" not in kinds(frozenset({"sqlglot/tokens.py"}))
    assert "failed_command" in kinds(frozenset({"sqlglot/tokens.py"}))


def test_reworking_a_file_the_session_created_is_not_a_label():
    made = edit("scratch.py", diff="--- /dev/null\n+++ b/scratch.py\n+x\n")
    s = session(made, edit("scratch.py", diff="-x\n+y\n"), edit("scratch.py", diff="-y\n+z\n"))
    assert not [
        p for p in pain_labels(s, {}, frozenset()) if p.signature.signal.value == "reworked_edit"
    ]


def test_hub_modules_are_imported_by_most_test_files():
    refs = {
        "sqlglot/expressions.py": frozenset(
            {f"tests/test_{n}.py" for n in "abc"} | {"sqlglot/x.py"}
        ),
        "sqlglot/rare.py": frozenset({"tests/test_a.py"}),
    }
    assert hub_modules(refs, cutoff=0.5) == frozenset({"sqlglot/expressions.py"})


def test_split_by_task_is_seeded_and_disjoint():
    ids = [f"t{i}" for i in range(20)]
    train, test = split_by_task(ids, test_fraction=0.3, seed=7)
    assert train.isdisjoint(test) and train | test == set(ids) and len(test) == 6
    assert split_by_task(ids, test_fraction=0.3, seed=7) == (train, test)
    assert split_by_task(ids, test_fraction=0.3, seed=8) != (train, test)


def test_auroc_counts_ties_as_half():
    assert auroc([True, False], [True, False]) == 1.0
    assert auroc([True, False, True, False], [False, False, False, False]) == 0.5
    with pytest.raises(ValueError):
        auroc([True, True], [True, False])


def scores_named(name, flags_by_session):
    per = tuple(
        SessionScores(
            task_id=f"t{i}",
            followed=f,
            flagged=g,
            recalled=(False,) * len(f),
            recall_hit=(None,) * len(f),
        )
        for i, (f, g) in enumerate(flags_by_session)
    )
    return OfflineScores(decider=name, per_session=per)


def test_fly_default_stays_with_counters_when_gap_is_small_or_unproven():
    sessions = [((True, False, True, False), (True, False, True, False)) for _ in range(30)]
    counters = scores_named("counters", sessions)
    same = scores_named("mushroom", sessions)
    verdict = fly_default([same], counters, seed=0)
    assert verdict.live == "counters"
    assert verdict.gap == 0.0


def test_fly_default_goes_fly_when_gap_clears_margin_and_ci_excludes_zero():
    good = ((True, False, True, False), (True, False, True, False))
    bad = ((True, False, True, False), (False, False, False, False))
    counters = scores_named("counters", [bad] * 30)
    fly = scores_named("mushroom", [good] * 30)
    verdict = fly_default([fly], counters, seed=0)
    assert verdict.live == "fly"
    assert verdict.gap == pytest.approx(0.5)
    assert verdict.ci_low > 0


def test_bootstrap_refuses_misaligned_sessions():
    a = scores_named("counters", [((True, False), (True, False))] * 3)
    b = scores_named("mushroom", [((True, False), (True, False))] * 2)
    with pytest.raises(ValueError):
        bootstrap_auroc_gap([b], a, seed=0)


def rows(*names):
    s = [((True, False), (True, False))]
    return {n: scores_named(n, s) for n in names}


def test_table_always_has_all_three_rows():
    table = render_table(rows("counters", "similarity", "fly"))
    for line in ("counters", "similarity", "fly"):
        assert line in table
    labelled = {
        line.split("|")[1].strip(): line for line in table.splitlines()[2:] if line.startswith("|")
    }
    assert labelled["counters"].split("|")[2].strip() == "reference"
    assert labelled["similarity"].split("|")[2].strip() == "reference"
    assert "under test" in labelled["fly"].split("|")[2]
    assert "random wiring" in labelled["fly"]
    assert "balanced accuracy (AUROC of the binary flag)" in table


def test_table_refuses_to_render_without_counters():
    with pytest.raises(MissingRowError) as err:
        render_table(rows("similarity", "fly"))
    assert "counters" in str(err.value)


def test_table_refuses_to_render_without_fly_or_similarity():
    with pytest.raises(MissingRowError):
        render_table(rows("counters", "similarity"))
    with pytest.raises(MissingRowError):
        render_table(rows("counters", "fly"))


def seed_scores(name, flagged_a, flagged_b):
    """Two sessions of two steps; step 0 is followed by a pain point."""
    return scores_named(name, [((True, False), flagged_a), ((True, False), flagged_b)])


def test_table_has_the_seed_averaged_fly_row_and_each_wiring_seed():
    seeds = {
        0: seed_scores("mushroom", (True, False), (True, False)),  # 1.0
        1: seed_scores("mushroom", (False, False), (False, False)),  # 0.5
        2: seed_scores("mushroom", (True, True), (True, True)),  # 0.5
    }
    table = render_table(rows("counters", "similarity"), fly_seeds=seeds)
    cells = {
        line.split("|")[1].strip(): [c.strip() for c in line.split("|")[2:-1]]
        for line in table.splitlines()[2:]
        if line.startswith("|")
    }
    assert list(cells) == [
        "counters",
        "similarity",
        "fly",
        "fly seed 0",
        "fly seed 1",
        "fly seed 2",
    ]
    assert cells["fly"][1] == "0.667"  # mean of 1.0, 0.5, 0.5
    assert "seed-averaged" in cells["fly"][0] and "under test" in cells["fly"][0]
    assert cells["fly seed 1"][1] == "0.500" and cells["fly seed 2"][1] == "0.500"
    assert cells["counters"][0] == "reference"


def test_table_footnotes_the_mushroom_recall_word_prefilter():
    table = render_table(rows("counters", "similarity", "fly"))
    assert "word pre-filter" in table.splitlines()[-1]
    assert "re-ranks similarity's own word-sharing candidates" in table
    fly_line = next(line for line in table.splitlines() if line.startswith("| fly"))
    assert "[1]" in fly_line


def test_table_refuses_a_fly_row_and_fly_seeds_together():
    with pytest.raises(ValueError):
        render_table(
            rows("counters", "similarity", "fly"),
            fly_seeds={0: seed_scores("mushroom", (True, False), (True, False))},
        )


def test_table_refuses_empty_fly_seeds():
    with pytest.raises(MissingRowError):
        render_table(rows("counters", "similarity"), fly_seeds={})


# --- fix round 1 ---

SCRATCH = "scratch.py"


def scratch_rework_session(sid, task):
    made = edit(SCRATCH, diff="--- /dev/null\n+++ b/scratch.py\n+x\n")
    records = session(made, edit(SCRATCH, diff="-x\n+y\n"), *[say("ok") for _ in range(6)])
    return [replace(r, session_id=sid, task_id=task) for r in records]


def test_learners_do_not_learn_from_rework_of_a_files_own_scratch():
    past = scratch_rework_session("h0", "t0")
    assert any(p.signature.signal.value == "reworked_edit" for p in mine_session(past, {})), "setup"
    history = History.from_sessions([past], fresh_ctx())
    visit = [replace(r, session_id="n0", task_id="u0") for r in session(view(SCRATCH), say("ok"))]
    scores = scored(Counters(min_count=1), [visit], history)
    assert not any(scores.per_session[0].flagged), "labels drop this point, so learners must too"


def test_a_trained_state_carries_over_to_the_next_replay():
    mushroom = Mushroom(seed=0, trouble_threshold=0.5)
    train = replay(
        mushroom,
        [trap_session(f"h{i}", f"t{i}") for i in range(3)],
        Start.fresh(),
        ctx=fresh_ctx(),
        seed=0,
    )
    assert train.state.updates == 3 * 10
    test = replay(
        mushroom,
        [trap_session("n0", "u0")],
        train.resume(),
        ctx=fresh_ctx(),
        seed=0,
    )
    assert test.state.updates == 4 * 10
    assert len(test.history.pain_points) > len(train.history.pain_points)
    assert len(test.scores.per_session) == 1, "only the new sessions are scored"
    cold = replay(
        mushroom, [trap_session("n0", "u0")], Start(train.history), ctx=fresh_ctx(), seed=0
    )
    assert cold.state.updates == 10


def test_learning_happens_after_the_session_in_step_order():
    seen = []

    class Recorder:
        name = "recorder"

        def initial_state(self, seed):
            return ()

        def decide(self, x, situation, state):
            seen.append(("decide", situation.session_prefix[-1].step, len(state)))
            return Counters().decide(x, situation, None)

        def learn(self, x, outcome, state):
            seen.append(("learn", len(state)))
            return state + (outcome,)

    replay(Recorder(), [trap_session("n0", "u0")], Start.fresh(), ctx=fresh_ctx(), seed=0)
    assert [e for e in seen if e[0] == "decide"] == [("decide", t, 0) for t in range(10)]
    assert seen[10:] == [("learn", n) for n in range(10)]


@pytest.mark.parametrize(
    ("gap", "low", "live"),
    [
        (MARGIN, 0.001, "fly"),  # exactly at the margin counts
        (MARGIN - 0.001, 0.001, "counters"),  # interval clear of 0 but gap too small
        (0.30, 0.0, "counters"),  # big gap, interval touches 0
        (0.30, -0.05, "counters"),  # big gap, interval crosses 0
        (0.30, 0.05, "fly"),
        (0.0, -0.1, "counters"),
    ],
)
def test_live_learner_needs_both_the_margin_and_an_interval_clear_of_zero(gap, low, live):
    assert live_learner(gap, low) == live


def test_fly_is_judged_on_the_average_of_its_wiring_seeds():
    good = ((True, False, True, False), (True, False, True, False))
    bad = ((True, False, True, False), (False, False, False, False))
    counters = scores_named("counters", [bad] * 30)
    seeds = [scores_named("mushroom", [good] * 30), scores_named("mushroom", [bad] * 30)]
    gap, low, high = bootstrap_auroc_gap(seeds, counters, seed=0)
    assert gap == pytest.approx(0.25)  # mean of +0.5 and 0.0
    assert low <= gap <= high


def test_recall_beyond_the_third_record_is_not_scored():
    past = [trap_session(f"h{i}", f"t{i}") for i in range(3)]
    history = History.from_sessions(past, fresh_ctx())
    cited = [r for r in history.candidates]
    hit = next(r for r in cited if r.step == 2)  # the failing run, cited by the pain point

    class Generous:
        name = "generous"

        def initial_state(self, seed):
            return None

        def decide(self, x, situation, state):
            from symbiont.core.slot import Decision

            fillers = (past[0][0], past[0][1], past[1][0])  # cite no pain point
            return Decision(trouble=None, why=(), recall=(*fillers, hit), reason_none=None)

        def learn(self, x, outcome, state):
            return None

    scores = scored(Generous(), [trap_session("n0", "u0")], history)
    assert scores.recall_at_3 == 0.0


def test_hubs_come_from_the_real_reference_shape(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "core.py").write_text("")
    (tmp_path / "pkg" / "rare.py").write_text("")
    (tmp_path / "tests" / "test_a.py").write_text("from pkg import core\nfrom pkg import rare\n")
    (tmp_path / "tests" / "test_b.py").write_text("import pkg.core\n")
    assert hub_modules(build_references(tmp_path), cutoff=0.5) == frozenset({"pkg/core.py"})


def test_sessions_without_a_task_id_are_dropped_loudly(caplog):
    keep = trap_session("a", "t1")
    lost = [replace(r, task_id=None) for r in trap_session("b", "t2")]
    with caplog.at_level("WARNING"):
        kept, dropped = drop_taskless([keep, lost])
    assert kept == [keep] and dropped == 1
    assert "1 session" in caplog.text


def test_replay_refuses_a_session_without_a_task_id():
    lost = [replace(r, task_id=None) for r in trap_session("b", "t2")]
    with pytest.raises(ValueError, match="task id"):
        scored(Counters(), [lost])


def test_two_different_sessions_sharing_an_id_are_refused():
    ctx = fresh_ctx()
    ctx.labels(trap_session("same", "t1"))
    with pytest.raises(ValueError, match="same id"):
        ctx.labels(quiet_session("same", "t1"))


def test_row_interval_uses_the_same_task_draws_as_the_gap():
    sessions = [((True, False, True, False), (True, False, False, False))] * 10 + [
        ((True, False, True, False), (True, False, True, False))
    ] * 10
    counters = scores_named(
        "counters", [((True, False, True, False), (False, False, False, False))] * 20
    )
    fly = scores_named("mushroom", sessions)
    value, low, high = bootstrap_auroc_interval([fly], seed=3)
    assert low <= value <= high
    gap = bootstrap_auroc_gap([fly], counters, seed=3)
    base = bootstrap_auroc_interval([counters], seed=3)
    assert gap.gap == pytest.approx(value - base[0])
    with pytest.raises(ValueError):
        bootstrap_auroc_interval([], seed=3)
