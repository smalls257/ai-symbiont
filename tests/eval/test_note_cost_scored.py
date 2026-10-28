"""Scored T46 rules: the verdict, the within-repository bootstrap, the consistency tag."""

import numpy as np
import pytest

from symbiont.eval.note_cost_logistic import Steps, out_of_fold_risks
from symbiont.eval.note_cost_scored import Verdict, consistent, stratified_draws, verdict


def ci(value, low, high=1.0):
    return {"value": value, "ci95_low": low, "ci95_high": high}


def benefits(**over):
    base = {
        v: ci(0.0, -0.1) for v in (Verdict.COUNTERS, Verdict.CLASSIFIER, Verdict.DENSE, Verdict.FLY)
    }
    base.update(over)
    return base


def test_nobody_earns_means_none():
    assert verdict(benefits(), {}) is Verdict.NONE


def test_a_winner_that_cannot_be_told_from_non_earning_counters_gives_none():
    earn = benefits(**{Verdict.FLY: ci(0.2, 0.05)})
    assert verdict(earn, {Verdict.FLY: ci(0.2, -0.01)}) is Verdict.NONE


def test_a_winner_that_ties_earning_counters_gives_counters():
    earn = benefits(**{Verdict.CLASSIFIER: ci(0.2, 0.05), Verdict.COUNTERS: ci(0.1, 0.01)})
    assert verdict(earn, {Verdict.CLASSIFIER: ci(0.1, -0.01)}) is Verdict.COUNTERS


def test_a_winner_clearly_above_counters_wins_and_ties_go_to_the_plainest():
    earn = benefits(**{Verdict.CLASSIFIER: ci(0.2, 0.05), Verdict.FLY: ci(0.2, 0.05)})
    gaps = {Verdict.CLASSIFIER: ci(0.2, 0.01), Verdict.FLY: ci(0.2, 0.01)}
    assert verdict(earn, gaps) is Verdict.CLASSIFIER
    assert verdict(benefits(**{Verdict.COUNTERS: ci(0.1, 0.02)}), {}) is Verdict.COUNTERS


def test_draws_resample_within_each_repository():
    draws = stratified_draws(["a", "a", "a", "b", "b"], seed=1, n_boot=50)
    assert np.all(draws[:, :3].sum(axis=1) == 3) and np.all(draws[:, 3:].sum(axis=1) == 2)


def test_the_consistency_tag_flags_a_sign_flip_only():
    assert consistent([0.1, 0.2, 0.0]) and not consistent([0.1, -0.05, 0.2])


def test_out_of_fold_risks_never_use_their_own_fold():
    rng = np.random.default_rng(0)
    features = rng.normal(size=(300, 3))
    labels = (features[:, 0] > 0.8).astype(float)
    fold = np.arange(300) % 3
    before = out_of_fold_risks(Steps(features, labels, fold), 1.0)
    flipped = labels.copy()
    flipped[fold == 1] = 1 - flipped[fold == 1]
    after = out_of_fold_risks(Steps(features, flipped, fold), 1.0)
    assert np.allclose(before[fold == 1], after[fold == 1])


from symbiont.eval.note_cost_scored_report import (  # noqa: E402
    _STACKS,  # noqa: E402
    PRIMARY,
    StackReuse,
    registered_options,
    scored_report,
    train_stack,
)
from symbiont.eval.note_delivery import NoteTrace  # noqa: E402


def traces(seed, signal, repo, n_tasks=8, sessions=2, steps=50):
    rng = np.random.default_rng(seed)
    found = []
    for task in range(n_tasks):
        for _ in range(sessions):
            followed = rng.random(steps) < 0.2
            risk = rng.random(steps) + signal * followed
            boundary = rng.random(steps) < 0.5
            columns = (followed, risk, boundary)
            found.append(NoteTrace(f"{repo}-{task}", *(tuple(c.tolist()) for c in columns)))
    return tuple(found)


def pair(seed, signal, repo):
    return (traces(seed, signal, repo), traces(seed + 50, signal, repo))


def runs(signal):
    repos = ("r1", "r2")

    def learner(seeds, blocks, base):
        return {
            s: {
                r: [pair(base + 7 * s + 13 * b + i, signal, r) for b in range(blocks)]
                for i, r in enumerate(repos)
            }
            for s in seeds
        }

    one = {
        "counters": learner([0], 1, 1),
        "logistic": learner([0], 2, 100),
        "dense": learner([0, 1], 2, 200),
        "fly": learner([0, 1], 1, 300),
    }
    return {"repo": one, "pool": one}


def test_the_scored_report_has_floors_counters_beside_fly_per_repo_and_a_verdict():
    result = scored_report(runs(2.5), seed=3)
    pooled = [r for r in result["rows"] if r["repo"] == "pooled" and r["option"] == PRIMARY]
    roles = {(r["start"], r["arm"]): r["role"] for r in pooled}
    assert roles[("repo", "counters")] == "reference" and roles[("repo", "logistic")] == "reference"
    assert roles[("repo", "fly")] == "under_test" and roles[("pool", "warn never")] == "floor"
    assert {r["repo"] for r in result["rows"]} == {"pooled", "r1", "r2"}
    assert result["verdict"]["live_warner"] != "none"
    assert all("consistent_across_repos" in r for r in pooled)


def test_noise_gives_no_live_warner():
    assert scored_report(runs(0.0), seed=3)["verdict"]["live_warner"] == "none"


def test_the_stack_cache_changes_nothing():
    built = runs(2.5)
    cached = scored_report(built, seed=3)
    fresh = scored_report(built, seed=3, reuse=StackReuse.FRESH)
    assert cached["chosen_on_train"] == fresh["chosen_on_train"]
    assert cached["rows"] == fresh["rows"]


def test_a_reused_id_is_caught_not_served():
    option = registered_options()[0]
    first, second = traces(1, 1.0, "r"), traces(2, 1.0, "r")
    _STACKS.clear()
    stack = train_stack(first, option)
    _STACKS[(id(second), option.rule, option.tiers)] = (first, stack)  # as if an id came back
    with pytest.raises(RuntimeError, match="reused"):
        train_stack(second, option)
    _STACKS.clear()
