from symbiont.eval.offline import OfflineScores, SessionScores
from symbiont.eval.selection_record import (
    Calibration,
    FinalScores,
    HubCheckout,
    calibration_record,
    hub_record,
    per_step_record,
    result_rows,
    split_record,
)

THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95)


def scores():
    session = SessionScores("t0", (True, False), (True, False), (False, False), (None, None))
    return OfflineScores("x", (session,))


def final_scores():
    return FinalScores(scores(), scores(), {0: scores(), 1: scores()})


def test_calibration_record_keeps_every_grid_score_and_the_chosen_value():
    cal = Calibration(
        counters_scores={1: 0.5, 2: 0.6},
        best_min_count=2,
        fly_scores={("mushroom", seed, thr): 0.5 for seed in (0, 1, 2) for thr in THRESHOLDS},
        best_threshold={0: 0.5, 1: 0.6, 2: 0.7},
    )
    record = calibration_record(cal)
    assert record["counters_min_count"] == {"scores": {"1": 0.5, "2": 0.6}, "chosen": 2}
    assert record["mushroom_threshold"]["1"]["chosen"] == 0.6
    assert set(record["mushroom_threshold"]["2"]["scores"]) == {str(thr) for thr in THRESHOLDS}


def test_per_step_record_lists_counters_similarity_then_each_fly_seed():
    assert list(per_step_record(final_scores())) == [
        "counters",
        "similarity",
        "fly seed 0",
        "fly seed 1",
    ]


def test_result_rows_label_the_fly_row_under_test_beside_the_references():
    rows = result_rows(final_scores())
    assert list(rows) == ["counters", "similarity", "fly", "fly seed 0", "fly seed 1"]
    assert rows["counters"]["label"] == rows["similarity"]["label"] == "reference"
    assert rows["fly"]["label"].startswith("under test")


def test_hub_record_lists_the_hub_modules_sorted():
    record = hub_record(HubCheckout("task", "2024-01-01", "abc123", 7), {"b.py", "a.py"})
    assert record["hub_modules"] == ["a.py", "b.py"]
    assert (record["task_id"], record["base_commit"], record["reference_files"]) == (
        "task",
        "abc123",
        7,
    )


def test_split_record_counts_tasks_and_sessions_of_each_split():
    record = split_record({"records": 9}, tasks=(2, 1), sessions=(5, 3), steps_test=4)
    assert record["records"] == 9
    assert (record["tasks_train"], record["tasks_test"]) == (2, 1)
    assert (record["sessions_train"], record["sessions_test"], record["steps_test"]) == (5, 3, 4)
