"""The scored T39 comparison: settings fixed on validation, one word per comparison.

Violation prevented: **Paper Tiger** (a meta start that loses reported as anything but
"worse") and **Silent Fallback** (a missing reference row scored as if it were there).
"""

import numpy as np
import pytest

from symbiont.eval.meta_start_scored import (
    ROLES,
    meta_scored_report,
    verdict_word,
)
from symbiont.eval.note_delivery import NoteTrace

REPOS = ("a/one", "b/two", "c/three")


def traces(rng, tasks, informative, sessions=4, steps=20):
    found = []
    for task in tasks:
        for _ in range(sessions):
            followed = rng.random(steps) < 0.25
            noise = rng.random(steps)
            risk = followed * 0.8 + 0.2 * noise if informative else noise
            found.append(
                NoteTrace(
                    task, tuple(map(bool, followed)), tuple(map(float, risk)), (True,) * steps
                )
            )
    return tuple(found)


def window(informative=(), worse=()):
    rows = {}
    scoring_tasks = [f"{r}-{i}" for r in REPOS for i in range(6)]
    for name in ROLES:
        good = name in informative
        validation = traces(np.random.default_rng(1), [f"v{i}" for i in range(8)], good)
        scoring = traces(np.random.default_rng(2), scoring_tasks, good and name not in worse)
        rows[name] = {0: (validation, scoring)}
    return rows


def repo_of():
    return {f"{r}-{i}": r for r in REPOS for i in range(6)}


def primary(body, window_name="early"):
    return next(
        b
        for b in body["blocks"]
        if b["option"] == body["primary_option"] and b["window"] == window_name
    )


def test_a_cold_start_that_ranks_trouble_beats_an_uninformative_meta_start_and_the_word_is_worse():
    body = meta_scored_report({"early": window({"fly cold start"})}, repo_of(), seed=3, n_boot=300)
    h1 = next(c for c in primary(body)["comparisons"] if c["what"] == "H1 fly")
    assert h1["verdict"] == "worse"
    assert h1["ci95_high"] < 0
    assert set(h1["per_repo"]) == set(REPOS)


def test_every_row_has_a_pooled_and_a_per_repository_line_beside_both_floors():
    body = meta_scored_report({"early": window()}, repo_of(), seed=3, n_boot=50)
    block = primary(body)
    pooled = {r["arm"] for r in block["rows"] if r["repo"] == "pooled"}
    assert pooled == set(ROLES) | {"warn never", "note at every allowed step"}
    assert {r["repo"] for r in block["rows"]} == {"pooled", *REPOS}
    # Identical rows earn identically (a random note beats a 0.25 heads-up price at this
    # trouble rate); the tie goes to the plainest row.
    assert block["best_row"] == "counters"


def test_settings_come_from_validation_only():
    # Informative on validation, noise on scoring: the setting is still the validation one.
    body = meta_scored_report(
        {"early": window({"counters"}, worse={"counters"})}, repo_of(), seed=3, n_boot=50
    )
    chosen = primary(body)["chosen_on_validation"]["counters"]["seed 0"]
    assert np.isfinite(chosen).any()


def test_a_missing_row_is_refused():
    rows = window()
    del rows["logistic + online calibrator"]
    with pytest.raises(ValueError, match="missing rows"):
        meta_scored_report({"early": rows}, repo_of(), seed=3, n_boot=10)


@pytest.mark.parametrize(
    ("low", "high", "word"), [(0.1, 0.3, "better"), (-0.1, 0.2, "tie"), (-0.3, -0.1, "worse")]
)
def test_the_verdict_word_reads_the_interval(low, high, word):
    assert verdict_word({"ci95_low": low, "ci95_high": high}) == word
