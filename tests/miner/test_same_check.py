"""The same check passing later, however it was spelled; and the cases that must stay silent.

Guards against a Paper Tiger miner: live sessions verify with a different invocation than the
one that failed, so exact-command matching produced zero lessons. Hand-written records only.
"""

from dataclasses import replace

import pytest

from record_builders import edit, run, session
from symbiont.miner.lessons import lessons_from
from symbiont.miner.resolutions import NOTHING_CHANGED, Resolution, resolution_of
from symbiont.miner.same_check import check_of, reruns_same_check
from symbiont.miner.signals.failed_command import find_failed_commands

PYTEST_FAIL = (
    "src/io.py:12: AssertionError\n"
    "FAILED tests/test_io.py::test_roundtrip - AssertionError\n1 failed in 0.3s"
)


def passes(failed_command, later_command):
    return reruns_same_check(run(failed_command, 1), run(later_command, 0, "ok"))


@pytest.mark.parametrize(
    ("failed", "later"),
    [
        ("pytest tests/test_io.py::test_roundtrip", "pytest tests/test_io.py"),
        ("pytest tests/test_io.py", "pytest tests/test_io.py -k roundtrip -q"),
        ("pytest tests/test_io.py::test_roundtrip -x", "python -m pytest tests/test_io.py"),
        ("cd /w && python -m pytest tests/test_io.py", "uv run pytest tests/test_io.py -q"),
        ("uv run --group dev pytest tests/test_io.py", "pytest tests"),
        ("pytest tests/test_io.py::test_a", "pytest"),
        ("npx jest src/a.test.ts -t name", "npm test"),
        ("go test ./pkg/x -run TestY", "go test ./pkg/..."),
        ("cargo test foo", "cargo test"),
        ("bundle exec rspec spec/a_spec.rb:12", "bundle exec rspec spec/a_spec.rb"),
        ("npx vitest run src/a.test.ts", "bunx vitest run src/a.test.ts"),
        ("pytest /abs/repo/tests/test_io.py", "pytest tests/test_io.py"),
    ],
)
def test_a_differently_spelled_run_of_the_same_check_matches(failed, later):
    assert passes(failed, later)


@pytest.mark.parametrize(
    ("failed", "later"),
    [
        ("pytest tests/test_io.py", "pytest tests/test_other.py"),
        ("pytest tests/test_io.py", "ruff check tests/test_io.py"),
        ("go test ./pkg/x", "go build ./pkg/x"),
        ("go test ./pkg/x", "go test ./pkg/y"),
        ("cargo test foo", "cargo test bar"),
        ("pytest", "pytest tests/test_io.py"),
        ("npm test", "npx jest src/a.test.ts"),
        ("npm run build", "npm test"),
        ("bundle exec rspec spec/a_spec.rb", "bundle exec rspec spec/b_spec.rb"),
    ],
)
def test_a_different_tool_or_disjoint_targets_do_not_match(failed, later):
    assert not passes(failed, later)


def test_a_flag_value_is_not_a_target():
    assert check_of("pytest tests/test_io.py -k other_name -n 4").targets == {"tests/test_io.py"}
    assert check_of("go test ./pkg/x -run TestY").targets == {"pkg/x"}


def test_a_still_failing_or_piped_failing_run_does_not_match():
    failed = run("pytest tests/test_io.py::t", 1, PYTEST_FAIL)
    assert not reruns_same_check(failed, run("pytest tests", 1, "2 failed"))
    assert not reruns_same_check(failed, run("pytest tests | tail", 0, "FAILED a.py::t - E\n"))


def lesson_steps(records):
    pain = find_failed_commands(records)
    (lesson,) = lessons_from(pain, records, frozenset())
    return lesson


def resolve(records):
    pain = find_failed_commands(records)[0]
    cited = [r for r in records if (r.session_id, r.step) in pain.record_refs]
    return resolution_of(pain, cited, records)


def test_node_id_failure_then_edit_then_file_pass_is_a_lesson():
    records = session(
        run("pytest tests/test_io.py::test_roundtrip", 1, PYTEST_FAIL),
        edit("src/io.py"),
        run("python -m pytest tests/test_io.py -q", 0, "4 passed"),
    )
    found = resolve(records)
    assert isinstance(found, Resolution)
    assert [r.command or r.files for r in found.steps] == [
        ("src/io.py",),
        "python -m pytest tests/test_io.py -q",
    ]
    assert lesson_steps(records)


def test_file_failure_then_edit_then_k_pass_is_a_lesson():
    records = session(
        run("pytest tests/test_io.py", 1, PYTEST_FAIL),
        edit("src/io.py"),
        run("pytest tests/test_io.py -k roundtrip", 0, "1 passed, 3 deselected"),
    )
    assert isinstance(resolve(records), Resolution)


def test_an_unrelated_test_passing_is_no_lesson():
    records = session(
        run("pytest tests/test_io.py::test_roundtrip", 1, PYTEST_FAIL),
        edit("src/io.py"),
        run("pytest tests/test_other.py", 0, "2 passed"),
    )
    assert not isinstance(resolve(records), Resolution)


def test_a_broader_run_that_still_fails_is_no_lesson():
    records = session(
        run("pytest tests/test_io.py::test_roundtrip", 1, PYTEST_FAIL),
        edit("src/io.py"),
        run("pytest tests", 1, "1 failed, 40 passed"),
    )
    assert not isinstance(resolve(records), Resolution)


def test_a_reworded_rerun_with_nothing_changed_is_not_a_fix():
    records = session(
        run("pytest tests/test_io.py::test_roundtrip", 1, PYTEST_FAIL),
        run("uv run pytest tests/test_io.py", 0, "4 passed"),
    )
    assert resolve(records) == NOTHING_CHANGED


def test_a_planned_red_failure_is_still_skipped():
    records = session(
        edit("tests/test_io.py", diff="-a\n+    assert load() == 3\n"),
        run("pytest tests/test_io.py::test_roundtrip", 1, PYTEST_FAIL),
        edit("src/io.py"),
        run("pytest tests/test_io.py", 0, "4 passed"),
    )
    assert find_failed_commands(records) == []


@pytest.mark.parametrize(
    ("harness", "failing", "passing"),
    [
        (
            "muse_code",
            "cd /work/xarray && python -m pytest xarray/tests/test_backends.py::t 2>&1 | tail -9",
            "cd /work/xarray && python -m pytest xarray/tests/test_backends.py -q 2>&1 | tail -5",
        ),
        (
            "claude_code",
            "uv run pytest xarray/tests/test_backends.py::test_open",
            "pytest xarray/tests/test_backends.py -k open",
        ),
    ],
)
def test_both_harness_shapes_produce_a_lesson(harness, failing, passing):
    records = [
        replace(r, harness=harness)
        for r in session(
            run(
                failing,
                1,
                "xarray/backends/api.py:40: KeyError\nFAILED xarray/tests/test_backends.py::t\n",
            ),
            edit("xarray/backends/api.py"),
            run(passing, 0, "12 passed in 1.1s"),
        )
    ]
    assert isinstance(resolve(records), Resolution)
    assert lesson_steps(records)
