"""The background job's file: running, done with N lessons at T, or failed and why.

Violation prevented: Black Box. A training that continues after the tool call returned must be
askable; a killed job reads as interrupted, never as running forever.
"""

from datetime import UTC, datetime, timedelta

from symbiont.service.nightly_job import (
    STALE_AFTER_S,
    JobPhase,
    JobState,
    job_path,
    job_sentence,
    read_job,
    write_job,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
STARTED = "2026-11-03T11:58:00+00:00"


def test_no_job_says_nothing(tmp_path):
    assert read_job(tmp_path, "p") is None
    assert job_sentence(tmp_path, "p", NOW) is None


def test_a_running_job_says_since_when_with_how_many_lessons_and_where_the_log_is(tmp_path):
    write_job(tmp_path, "p", JobState(JobPhase.RUNNING, STARTED, 12))
    said = job_sentence(tmp_path, "p", NOW)
    assert said is not None
    assert said.startswith(f"training job: running on 12 lessons since {STARTED}")
    assert "job.log" in said


def test_a_finished_job_says_done_with_lessons_and_time(tmp_path):
    write_job(tmp_path, "p", JobState(JobPhase.DONE, STARTED, 12, "2026-11-03T12:00:00+00:00"))
    assert job_sentence(tmp_path, "p", NOW) == (
        "training job: done on 12 lessons at 2026-11-03T12:00:00+00:00"
    )


def test_a_failed_job_says_why(tmp_path):
    state = JobState(
        JobPhase.FAILED, STARTED, 12, "2026-11-03T12:00:00+00:00", "the trainer exited 1"
    )
    write_job(tmp_path, "p", state)
    assert job_sentence(tmp_path, "p", NOW) == (
        "training job: failed at 2026-11-03T12:00:00+00:00: the trainer exited 1"
    )


def test_a_job_that_began_long_ago_and_never_finished_reads_as_interrupted(tmp_path):
    long_ago = (NOW - timedelta(seconds=STALE_AFTER_S + 60)).isoformat()
    write_job(tmp_path, "p", JobState(JobPhase.RUNNING, long_ago, 3))
    said = job_sentence(tmp_path, "p", NOW)
    assert said is not None and "failed" in said and "interrupted" in said


def test_an_unreadable_file_is_said_not_ignored(tmp_path):
    job_path(tmp_path, "p").parent.mkdir(parents=True)
    job_path(tmp_path, "p").write_text("{nope", encoding="utf-8")
    said = job_sentence(tmp_path, "p", NOW)
    assert said is not None and "unusable" in said


def test_a_downloading_job_says_how_many_gigabytes_of_how_many(tmp_path):
    state = JobState(JobPhase.DOWNLOADING, STARTED, 12, None, "", 1_100_000_000, 2_500_000_000)
    write_job(tmp_path, "p", state)
    said = job_sentence(tmp_path, "p", NOW)
    assert said is not None and "training job: downloading model 1.1 of 2.5 GB" in said


def test_a_downloading_job_before_the_size_is_known_says_just_downloading(tmp_path):
    write_job(tmp_path, "p", JobState(JobPhase.DOWNLOADING, STARTED, 12))
    said = job_sentence(tmp_path, "p", NOW)
    assert said is not None and "training job: downloading model since" in said


def test_a_downloading_job_that_began_over_three_hours_ago_reads_as_interrupted(tmp_path):
    write_job(tmp_path, "p", JobState(JobPhase.DOWNLOADING, STARTED, 12))
    said = job_sentence(tmp_path, "p", NOW + timedelta(seconds=STALE_AFTER_S + 1))
    assert said is not None and "interrupted" in said
