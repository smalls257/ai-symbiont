"""The "Use: ..." chip on Add context suggests the clean error line, never the raw quote."""

from dataclasses import replace

from story_builders import owners_lesson
from symbiont.service.dashboard_view import _lesson


def test_the_chip_is_the_what_broke_error_line_not_the_raw_output():
    lesson = replace(owners_lesson(), quote="$ pnpm api:generate 2>&1\nELIFECYCLE\n" + "x" * 300)
    chip = _lesson(1, lesson, None, None, frozenset())["exampleContext"]
    assert chip.startswith("`identity.controller.ts:47`") and "ELIFECYCLE" not in chip
    assert "$ " not in chip


def test_with_no_error_line_there_is_no_suggestion():
    bare = replace(owners_lesson(), error_lines=(), quote="$ x\nExit status 1")
    assert _lesson(1, bare, None, None, frozenset())["exampleContext"] == ""
