"""The meta-start comparison table (T39): every row beside the floor, per window.

Violation prevented: **Paper Tiger**. A meta-start row without counters, the pool classifier
and the adapting classifier beside it could not be told from a win.
"""

import numpy as np
import pytest

from symbiont.eval.meta_start import EARLY_SESSIONS
from symbiont.eval.meta_start_report import (
    ROLES,
    WINDOWS,
    meta_report,
    note_traces,
    window_of,
)

REPOS = [f"r{i}" for i in range(10)]


def repo_traces(repo, rng, informative):
    sessions = EARLY_SESSIONS + 3
    followed = [rng.random(15) < 0.25 for _ in range(sessions)]
    noise = [rng.random(15) for _ in range(sessions)]
    risks = [y * 0.8 + 0.2 * n if informative else n for y, n in zip(followed, noise, strict=True)]
    boundary = [np.ones(15, dtype=bool) for _ in range(sessions)]
    return note_traces(repo, followed, risks, boundary)


def arms(informative_rows):
    built = {}
    for name in ROLES:
        rng = np.random.default_rng(7)  # same labels for every row
        traces = tuple(
            t for repo in REPOS for t in repo_traces(repo, rng, name in informative_rows)
        )
        built[name] = {0: traces}
    return built


def test_the_window_splits_each_repository_at_its_tenth_session():
    traces = arms(set())["counters"][0]
    early, late = (window_of(traces, w) for w in WINDOWS)
    assert len(early) == EARLY_SESSIONS * len(REPOS)
    assert len(late) == 3 * len(REPOS)
    with pytest.raises(ValueError, match="window"):
        window_of(traces, "first 5")


def test_every_row_and_the_floor_appear_in_each_window_and_option():
    body = meta_report(arms({"fly meta start"}), seed=1, n_boot=50)
    for window in WINDOWS:
        for option in body["options"]:
            names = {
                r["arm"] for r in body["rows"] if r["window"] == window and r["option"] == option
            }
            assert names == set(ROLES) | {"warn never"}
    assert body["repos"] == len(REPOS)


def test_an_informative_meta_start_shows_as_a_positive_paired_difference():
    body = meta_report(arms({"fly meta start"}), seed=1, n_boot=200)
    gap = next(
        d
        for d in body["differences"]
        if d["what"] == "fly meta start minus fly cold start"
        and d["window"] == WINDOWS[0]
        and d["option"] == "a_heads_up_gain_1"
    )
    assert gap["value"] > 0 and gap["ci95_low"] > 0


def test_a_missing_reference_row_is_refused():
    partial = arms(set())
    del partial["logistic + online calibrator"]
    with pytest.raises(ValueError, match="missing rows"):
        meta_report(partial, seed=1, n_boot=10)
