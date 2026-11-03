"""Expected-versus-actual lines survive from every runner, capped at whole lines, scrubbed."""

from symbiont.miner.failure_excerpt import EXCERPT_CHARS, assertion_excerpt

PYTEST = """\
E   AssertionError: "DATE_TRUNC('HOUR', CAST('2026[15 chars]MP))" != "CAST(DATE_TRUNC('HOUR'"
E   - DATE_TRUNC('HOUR', CAST('2026-01-01 00:00:00' AS TIMESTAMP))
E   + CAST(DATE_TRUNC('HOUR', CAST('2026-01-01 00:00:00' AS TIMESTAMP)) AS TIMESTAMP)
E   ? +++++                                                            ++++++++++++++
"""
JEST = """\
  expect(received).toBe(expected) // Object.is equality

  Expected: 4
  Received: 5
"""
CARGO = """\
thread 'adds' panicked at src/lib.rs:9:5:
assertion `left == right` failed
  left: 4
 right: 5
"""
GO = """\
--- FAIL: TestAdd (0.00s)
    add_test.go:12: got 5, want 4
"""


def test_pytest_keeps_the_diff_lines_and_drops_the_hint_line():
    lines = assertion_excerpt(PYTEST)
    assert lines[0] == "AssertionError"
    assert lines[1].startswith("- DATE_TRUNC(")
    assert lines[2].startswith("+ CAST(DATE_TRUNC(")
    assert not any(line.startswith("?") for line in lines)


def test_jest_expected_and_received():
    assert assertion_excerpt(JEST)[-2:] == ("Expected: 4", "Received: 5")


def test_cargo_left_and_right():
    assert assertion_excerpt(CARGO) == (
        "assertion `left == right` failed",
        "left: 4",
        "right: 5",
    )


def test_go_got_and_want():
    assert assertion_excerpt(GO) == ("--- FAIL: TestAdd (0.00s)", "add_test.go:12: got 5, want 4")


def test_cap_cuts_at_a_line_boundary():
    long = "E   - " + "x" * 120 + "\nE   + " + "y" * 120 + "\nE   + " + "z" * 120 + "\n"
    lines = assertion_excerpt(long)
    assert len(lines) == 2 and len(" ".join(lines)) <= EXCERPT_CHARS


def test_an_unknown_runner_yields_nothing():
    assert assertion_excerpt("all good\nbye") == ()


def test_credentials_are_scrubbed():
    token = "gh" + "p_" + "x" * 36
    out = assertion_excerpt(f"E   - token\nE   + {token}\n")
    assert token not in " ".join(out)
