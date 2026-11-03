"""The nightly state as the user reads it: never trained, trained on N lessons at T, or stale.

Violation prevented: Silent Fallback. A record that cannot be read, or that was written for other
lessons, reads as stale in words; it never reads as trained and never as never-trained.
"""

import json

import pytest

from nightly_support import PROJECT, failed_command_lesson
from symbiont.service.nightly import (
    RECORD,
    NightlyJudges,
    NightlyRecord,
    NightlyReport,
    NightlyState,
    lessons_digest,
    previous_judge_url,
    write_record,
)

pytestmark = pytest.mark.periphery
LESSONS = [failed_command_lesson(i) for i in range(3)]
WHEN = "2026-11-03T03:00:00+00:00"


def record_for(lessons, count=None):
    return NightlyRecord(
        lessons_digest(lessons), "http://127.0.0.1:8861", count or len(lessons), WHEN, "mlx"
    )


def test_no_record_reads_as_never_trained(tmp_path):
    report = NightlyJudges(tmp_path).report(PROJECT, LESSONS)
    assert report.state is NightlyState.NEVER
    assert report.sentence() == "never trained (run `symbiont nightly`)"


def test_a_record_for_todays_lessons_reads_as_trained_with_count_and_time(tmp_path):
    write_record(tmp_path, PROJECT, record_for(LESSONS))
    report = NightlyJudges(tmp_path).report(PROJECT, LESSONS)
    assert (report.state, report.lessons, report.trained_at) == (NightlyState.TRAINED, 3, WHEN)
    assert report.sentence() == f"trained on 3 lessons at {WHEN}"


def test_new_lessons_since_the_night_read_as_stale_and_say_what_was_trained(tmp_path):
    write_record(tmp_path, PROJECT, record_for(LESSONS))
    report = NightlyJudges(tmp_path).report(PROJECT, [*LESSONS, failed_command_lesson(9)])
    assert report.state is NightlyState.STALE
    assert report.sentence().startswith(
        "stale: your lessons changed since; last trained on 3 lessons"
    )


def test_an_unreadable_record_reads_as_stale_with_the_reason_never_raises(tmp_path):
    (tmp_path / PROJECT).mkdir()
    (tmp_path / PROJECT / RECORD).write_text("{not json")
    report = NightlyJudges(tmp_path).report(PROJECT, LESSONS)
    assert report.state is NightlyState.STALE
    assert "unusable" in report.sentence()


def test_a_record_from_the_script_without_count_or_time_still_reads(tmp_path):
    (tmp_path / PROJECT).mkdir()
    old = {"lessons_digest": lessons_digest(LESSONS), "judge_url": "http://127.0.0.1:1"}
    (tmp_path / PROJECT / RECORD).write_text(json.dumps(old))
    report = NightlyJudges(tmp_path).report(PROJECT, LESSONS)
    assert report.sentence() == "trained on lessons"


def test_writing_a_record_is_atomic_and_leaves_no_partial_file(tmp_path):
    path = write_record(tmp_path, PROJECT, record_for(LESSONS))
    assert [p.name for p in path.parent.iterdir()] == [RECORD]
    assert json.loads(path.read_text())["backend"] == "mlx"


def test_the_previous_judge_url_comes_from_the_last_record_or_is_none(tmp_path):
    assert previous_judge_url(tmp_path, PROJECT) is None
    write_record(tmp_path, PROJECT, record_for(LESSONS))
    assert previous_judge_url(tmp_path, PROJECT) == "http://127.0.0.1:8861"


def test_the_report_sentence_without_a_time_omits_it():
    assert NightlyReport(NightlyState.TRAINED, 2).sentence() == "trained on 2 lessons"
