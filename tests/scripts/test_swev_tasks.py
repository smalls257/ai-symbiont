"""SWE-bench Django pick: date order, kept difficulties, labels only; the lessons filter."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "swev"))

import select_lessons  # noqa: E402
import swev_tasks  # noqa: E402
import verify_images  # noqa: E402

PATCH = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old_line = compute_old_value(arg)\n+x = 1\n"


def _row(num: int, created: str, difficulty: str = "<15 min fix", repo: str = "django/django"):
    return {
        "instance_id": f"django__django-{num}",
        "repo": repo,
        "created_at": created,
        "difficulty": difficulty,
        "version": "3.0",
        "patch": PATCH,
        "problem_statement": "secret task text",
        "FAIL_TO_PASS": json.dumps(["t1"]),
        "PASS_TO_PASS": json.dumps(["t2", "t3"]),
        "image": f"swebench/sweb.eval.x86_64.django_1776_django-{num}:latest",
    }


def _rows(count: int) -> list[dict]:
    return [_row(num, f"2019-01-{num:02d}T00:00:00Z") for num in range(count, 0, -1)]


@pytest.fixture
def small_phases(monkeypatch):
    monkeypatch.setattr(swev_tasks, "HISTORY_N", 3)
    monkeypatch.setattr(swev_tasks, "LATER_N", 2)


def test_phases_split_by_date_and_drop_hard_and_other_repos(small_phases):
    rows = _rows(6) + [
        _row(90, "2018-01-01T00:00:00Z", difficulty="1-4 hours"),
        _row(91, "2018-01-02T00:00:00Z", repo="sympy/sympy"),
    ]
    phases = swev_tasks.select_phases(rows)
    assert [r["instance_id"][-1] for r in phases["history"]] == ["1", "2", "3"]
    assert [r["instance_id"][-1] for r in phases["later"]] == ["4", "5"]


def test_date_ties_break_on_instance_id(small_phases):
    rows = [_row(num, "2019-01-01T00:00:00Z") for num in (5, 3, 4, 1, 2)]
    ids = [r["instance_id"] for r in swev_tasks.select_phases(rows)["history"]]
    assert ids == sorted(ids)


def test_too_few_rows_raise_instead_of_a_short_list(small_phases):
    with pytest.raises(swev_tasks.TaskSelectionError, match="needs 5"):
        swev_tasks.select_phases(_rows(4))


def test_candidates_carry_labels_never_text(small_phases):
    entries = swev_tasks.candidates(swev_tasks.select_phases(_rows(5)))
    assert [e["order"] for e in entries] == [1, 2, 3, 4, 5]
    first = entries[0]
    assert first["gold_changed_lines"] == 2
    assert (first["n_fail_to_pass"], first["n_pass_to_pass"]) == (1, 2)
    assert "secret" not in json.dumps(entries)
    assert "patch" not in first
    assert swev_tasks.pilot_ids(entries) == [e["instance_id"] for e in entries[:3]]


def test_tag_url_defaults_to_latest_and_needs_a_namespace():
    assert verify_images.tag_url("swebench/img").endswith("/swebench/repositories/img/tags/latest")
    with pytest.raises(ValueError, match="namespace"):
        verify_images.tag_url("img:latest")


TASKS = {
    "tasks": [
        {"instance_id": "django__django-1", "phase": "history"},
        {"instance_id": "django__django-2", "phase": "later"},
    ]
}
ROWS = [{"instance_id": "django__django-2", "patch": PATCH}]


def _lesson(lesson_id: str, repo: str = "django/django", **extra) -> dict:
    return {"lesson_id": lesson_id, "repo": repo, "check": "run the one test module"} | extra


def test_lessons_filter_by_named_repos():
    lessons = [_lesson("a"), _lesson("b", repo="tobymao/sqlglot")]
    kept, counts = select_lessons.select(lessons, {"django/django"}, TASKS, ROWS)
    assert [lesson["lesson_id"] for lesson in kept] == ["a"]
    both, _ = select_lessons.select(lessons, {"django/django", "tobymao/sqlglot"}, TASKS, ROWS)
    assert len(both) == 2
    assert counts["kept"] == 1


def test_untagged_lesson_raises():
    with pytest.raises(ValueError, match="no repo tag"):
        select_lessons.select([{"lesson_id": "x"}], {"django/django"}, TASKS, ROWS)


@pytest.mark.parametrize("source", ["django__django-2", "django__django-77"])
def test_lesson_from_outside_phase_1_raises(source):
    with pytest.raises(select_lessons.HoldOutViolationError, match=source):
        select_lessons.select([_lesson("a", instance_id=source)], {"django/django"}, TASKS, ROWS)


def test_lesson_quoting_a_scored_gold_line_is_dropped_short_lines_are_not():
    quoting = _lesson("q", fix={"after": "  old_line = compute_old_value(arg)  "})
    short = _lesson("s", fix="x = 1")
    kept, counts = select_lessons.select([quoting, short], {"django/django"}, TASKS, ROWS)
    assert [lesson["lesson_id"] for lesson in kept] == ["s"]
    assert counts["dropped_leak"] == ["q"]
