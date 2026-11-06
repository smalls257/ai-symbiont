"""The Pain points stage's page data: facts, lessons with session indexes, strips, KPIs."""

from dataclasses import replace
from datetime import date

from record_builders import edit, run, session
from symbiont.miner.churn import FileChurn
from symbiont.miner.lesson_context import Review, Verdict
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.patterns import StrugglePattern
from symbiont.miner.strips import Lane, SessionStrip, StripStep
from symbiont.miner.struggle import MINUTES_PER_TURN, SessionFacts
from symbiont.miner.trained import lesson_id
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot

TODAY = date(2026, 11, 2)
IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"
DATES = {"a": date(2026, 9, 3), "b": date(2026, 10, 20), "c": date(2026, 10, 31)}


def lessons_in(*session_ids):
    steps = []
    for sid in session_ids:
        steps += [
            replace(step, project="demo", session_id=sid)
            for step in session(
                run("pytest tests/test_parser.py", 1, IMPORT),
                edit("app/parser.py", diff="-a\n+def parse(text):\n"),
                run("pytest tests/test_parser.py", 0, "1 passed"),
            )
        ]
    return lessons_from(mine_history(sessions_of(steps), {}), steps)


def facts(sid, *, themes=(), patterns=(), turns=0, outcomes=None, struggled=False):
    return SessionFacts(
        sid, f"task {sid}", frozenset(themes), frozenset(patterns), turns, outcomes or {}, struggled
    )


FACTS = [
    facts(
        "a",
        themes=["parser"],
        patterns=[StrugglePattern.WRONG_API],
        turns=10,
        outcomes={"code_fix": 2, "never": 1},
        struggled=True,
    ),
    facts("b", themes=["parser", "window"], turns=4, outcomes={"corrected_command": 1}),
    facts("c", themes=["window"], turns=0),
]


def stage_of(*, strips=(), churn=(), lessons=None, facts_=FACTS):
    lessons = lessons_in("a", "b") if lessons is None else lessons
    view = RepoView("demo", lessons, {}, DATES, facts=facts_, strips=strips, churn=churn)
    return dashboard_snapshot(view, TODAY)["stage"]


def test_the_page_data_lists_lessons_with_their_session_indexes():
    stage = stage_of()

    (lesson,) = stage["lessons"]
    assert lesson["sessions"] == [0, 1] and lesson["occurrences"] == 2
    assert "pytest" in lesson["title"] and lesson["fix"].startswith("you ")


def test_the_page_data_draws_a_strip_for_the_densest_session_of_every_theme_and_pattern():
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    steps = (
        StripStep(0, Lane.YOU, "you"),
        StripStep(3, Lane.FAILED, f"curl {token}"),
        StripStep(4, Lane.CODE_EDIT, "app/parser.py"),
    )
    stage = stage_of(strips=[SessionStrip("b", "task b", 2000, steps, 3)])

    strip = stage["strips"]["1"]
    assert strip["task"] == "task b" and strip["burst"] == 2000
    assert [s[:2] for s in strip["steps"]] == [[0, "you"], [3, "failed"], [4, "edit"]]
    assert token not in str(strip)


def test_the_kpis_add_up_to_the_session_facts():
    kpis = stage_of()["kpis"]

    assert kpis["turnsLost"] == 14
    assert kpis["minutes"] == round(14 * MINUTES_PER_TURN)
    assert kpis["lessonsReady"] == 1
    assert (kpis["failures"], kpis["knownFixes"], kpis["knownFixPercent"]) == (4, 3, 75)


def test_facts_keep_the_session_order_and_the_hand_set_themes():
    stage = stage_of()

    assert [f["turns"] for f in stage["facts"]] == [10, 4, 0]
    assert stage["facts"][0]["patterns"] == ["wrong_api"] and stage["facts"][0]["struggled"]
    assert stage["themeWords"] == ["parser", "window"]


def test_every_pattern_has_a_name_a_meaning_and_the_help_that_fits():
    stage = stage_of()

    assert {p["id"] for p in stage["patterns"]} == {p.value for p in StrugglePattern}
    assert all(p["name"] and p["short"] and p["means"] and p["help"] for p in stage["patterns"])
    by_id = {p["id"]: p for p in stage["patterns"]}
    assert by_id["tests_not_found"]["teachable"] and not by_id["rerunning"]["teachable"]


def test_files_carry_the_sessions_that_edited_them_so_the_files_tab_can_follow_a_selection():
    churn = [FileChurn("app/parser.py", "a", 6), FileChurn("app/parser.py", "b", 1)]
    stage = stage_of(churn=churn + [FileChurn("app/other.py", "c", 1)])

    top = stage["files"][0]
    assert (top["file"], top["edits"], top["sessions"]) == ("app/parser.py", 7, [0, 1])
    assert stage["months"] == ["2026-09", "2026-10"] and stage["monthOf"] == [0, 1, 1]


def test_a_store_mined_before_session_facts_has_no_stage():
    assert stage_of(facts_=[]) is None


def test_the_snapshot_carries_the_stage():
    view = RepoView("demo", lessons_in("a", "b"), {}, DATES, facts=FACTS)
    assert dashboard_snapshot(view, TODAY)["stage"]["kpis"]["turnsLost"] == 14


def test_what_mining_held_back_is_told_in_a_sentence():
    from symbiont.miner.screen import HoldReason

    view = RepoView("demo", lessons_in("a", "b"), {}, DATES, facts=FACTS)
    held = RepoView("demo", [], {}, DATES, facts=FACTS, held_back={HoldReason.NO_FIX_SHOWN: 3})
    assert dashboard_snapshot(view, TODAY)["stage"]["heldBack"] == ""
    assert dashboard_snapshot(held, TODAY)["stage"]["heldBack"] == "held back 3: 3 no fix shown"


def test_a_reviewers_merge_gives_the_stage_the_same_lesson_rows_as_the_pain_point_list():
    first = lessons_in("a")
    other = [
        replace(
            lesson,
            pain_point=replace(
                lesson.pain_point,
                signature=replace(
                    lesson.pain_point.signature, key=("pytest", "tests/test_other.py", "KeyError")
                ),
            ),
        )
        for lesson in lessons_in("b")
    ]
    merge = {lesson_id(other[0]): Review(Verdict.MISTAKE, merge_with=lesson_id(first[0]))}
    view = RepoView("demo", [*first, *other], {}, DATES, reviews=merge, facts=FACTS)

    data = dashboard_snapshot(view, TODAY)

    (row,) = data["stage"]["lessons"]
    assert row["id"] == data["painPoints"][0]["lessonId"]
    assert row["sessions"] == [0, 1]


def test_the_stage_says_how_a_lesson_and_a_burst_are_decided_so_the_page_hardcodes_neither():
    view = RepoView("demo", lessons_in("a", "b"), {}, DATES, facts=FACTS, min_sessions=3)
    stage = dashboard_snapshot(view, TODAY)["stage"]

    assert (stage["minSessions"], stage["burstFailures"], stage["burstSteps"]) == (3, 3, 10)


def test_a_strip_carries_its_shaded_bursts_and_the_full_step_count():
    fails = tuple(StripStep(n, Lane.FAILED, "pytest x") for n in (1, 2, 3, 40))
    stage = stage_of(strips=[SessionStrip("b", "task b", 1000, fails, 900)])

    strip = stage["strips"]["1"]
    assert strip["bursts"] == [[1, 3]] and strip["total"] == 900


def test_the_empty_state_names_the_main_hold_reason_and_the_rule():
    """Failure guarded against: telling a developer "nothing repeated" when no fix was shown."""
    from symbiont.miner.screen import HoldReason

    held = {HoldReason.NO_FIX_SHOWN: 75, HoldReason.TOO_FEW_SESSIONS: 6}
    view = RepoView("demo", [], {}, DATES, facts=FACTS, held_back=held, min_sessions=2)

    said = dashboard_snapshot(view, TODAY)["noLessons"]

    assert "a lesson needs a fix shown in the same session" in said
    assert "75 of 81" in said
    assert "min_sessions" in said and "only" in said and "too few sessions" in said
    assert "Nothing has repeated" not in said


def test_the_empty_state_for_too_few_sessions_points_at_the_setting():
    from symbiont.miner.screen import HoldReason

    view = RepoView(
        "demo",
        [],
        {},
        DATES,
        facts=FACTS,
        held_back={HoldReason.TOO_FEW_SESSIONS: 4},
        min_sessions=3,
    )
    said = dashboard_snapshot(view, TODAY)["noLessons"]
    assert "fewer than 3 sessions" in said and "symbiont settings mining min_sessions" in said


def test_the_failures_never_shown_a_fix_are_listed_by_cost_with_the_hold_reason():
    from symbiont.miner.painpoint import Signal, Signature
    from symbiont.store.held_back import StruggleGroup

    small = StruggleGroup(Signature(Signal.FAILED_COMMAND, ("make", "lint", "exit 2")), 2, 3)
    big = StruggleGroup(Signature(Signal.FAILED_COMMAND, ("pytest", "-", "exit 1")), 5, 9)
    view = RepoView("demo", [], {}, DATES, facts=FACTS, struggle=[small, big])

    groups = dashboard_snapshot(view, TODAY)["struggle"]

    assert [g["occurrences"] for g in groups] == [9, 3]
    assert groups[0]["reason"] == "no fix shown" and groups[0]["what"] and groups[0]["minutes"] > 0
