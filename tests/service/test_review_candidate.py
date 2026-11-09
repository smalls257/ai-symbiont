"""A review candidate carries what a reviewer needs; the developer's words outrank its verdict.

Failures guarded against: Paper Tiger (a candidate with no error line, fix or context is judged
noise by a reviewer who could not see what broke) and Silent Fallback (a model verdict quietly
silencing a lesson the developer annotated).
"""

from dataclasses import replace
from datetime import date

from record_builders import edit, run, say, session, user
from store_builders import save_lessons
from symbiont.miner.lesson_context import LessonContext, Priority, Review, Verdict
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.trained import lesson_id
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
from symbiont.service.review_candidate import review_candidate
from symbiont.store.local import Store

LONG_OUTPUT = (
    "tests/test_refund.py F\n"
    + "noise line\n" * 60
    + "E   AssertionError: assert 12.5 == 13.0\n"
    + "FAILED tests/test_refund.py::test_rounding - AssertionError: assert 12.5 == 13.0\n"
    + "1 failed, 4 passed in 0.52s\n"
)
SECRET = "to" + "ken=Zq7Lm2Xv9Rt4Wp8K"
FOOTER_ONLY = "1 failed, 4 passed in 0.52s"


def pytest_lessons():
    steps = session(
        run("pytest tests/test_refund.py -q", 1, LONG_OUTPUT),
        edit("src/refund.py", diff="-round(x)\n+round(x, 1)\n"),
        run("pytest tests/test_refund.py -q", 0, "5 passed in 0.5s"),
    )
    steps = [replace(step, project="demo", session_id="s1") for step in steps]
    return lessons_from(mine_history(sessions_of(steps), {}), steps, frozenset())


def test_the_candidate_names_the_command_the_error_the_fix_and_the_files():
    (lesson,) = pytest_lessons()

    candidate = review_candidate(lesson, None)

    assert candidate["command"] == "pytest tests/test_refund.py"
    assert any("AssertionError: assert 12.5 == 13.0" in line for line in candidate["error_lines"])
    assert any("test_rounding" in line for line in candidate["error_lines"])
    assert candidate["fix"] and "refund.py" in candidate["fix"]
    assert "round(x, 1)" not in " ".join(candidate["also_changed"])
    assert "src/refund.py" in candidate["files"]
    assert FOOTER_ONLY not in candidate["error"] and candidate["error"]
    assert "developer_said" not in candidate


def test_the_developers_words_travel_with_the_candidate():
    (lesson,) = pytest_lessons()
    words = LessonContext("Rounding bugs cost us money.", False, Priority.HIGH)

    candidate = review_candidate(lesson, words)

    assert candidate["developer_said"] == "Rounding bugs cost us money."
    assert candidate["developer_priority"] == "high"
    assert candidate["developer_marked_intentional"] is False


def test_a_credential_in_the_error_line_is_scrubbed():
    steps = session(run("pytest -q", 1, f"E   AssertionError: {SECRET} rejected\n"))
    steps = [replace(step, project="demo", session_id="s1") for step in steps]
    (lesson,) = lessons_from(mine_history(sessions_of(steps), {}), steps, frozenset())

    assert SECRET.split("=")[1] not in str(review_candidate(lesson, None))


def test_a_noise_verdict_does_not_silence_a_lesson_the_developer_annotated(tmp_path):
    from symbiont.service.effective_context import effective_contexts

    (lesson,) = pytest_lessons()
    ident = lesson_id(lesson)
    store = Store.open(tmp_path / "s.db")
    store.curation.save_review("demo", ident, Review(Verdict.NOISE))
    assert effective_contexts(store, "demo")[ident].intentional

    save_lessons(store, "demo", [], [lesson], held_out_tasks=frozenset())
    store.contexts.save(ident, "demo", LessonContext(""))

    kept = effective_contexts(store, "demo")[ident]
    assert not kept.intentional


def test_the_dashboard_shows_the_conflict_only_for_an_annotated_lesson():
    (lesson,) = pytest_lessons()
    ident = lesson_id(lesson)
    reviews = {ident: Review(Verdict.NOISE)}
    contexts = {ident: LessonContext("Matters.")}
    today = date(2026, 11, 2)

    flagged = dashboard_snapshot(
        RepoView("demo", [lesson], contexts, {}, reviews, annotated=frozenset({ident})), today
    )
    plain = dashboard_snapshot(RepoView("demo", [lesson], {}, {}, reviews), today)

    assert flagged["lessons"][0]["reviewConflict"] == "noise"
    assert plain["lessons"][0]["reviewConflict"] is None


def asked_lessons(user_text="fix the refund rounding", intent="I will round to one place"):
    steps = session(
        user(user_text),
        say(intent),
        run("pytest tests/test_refund.py -q", 1, LONG_OUTPUT),
        edit("src/refund.py", diff="-round(x)\n+round(x, 1)\n"),
        run("pytest tests/test_refund.py -q", 0, "5 passed in 0.5s"),
    )
    steps = [replace(step, project="demo", session_id="s1") for step in steps]
    return lessons_from(mine_history(sessions_of(steps), {}), steps, frozenset())


def test_the_review_candidate_carries_the_turns_around_the_failure_scrubbed():
    (lesson,) = asked_lessons(f"fix it, my {SECRET} works", "I will retry")

    candidate = review_candidate(lesson, None)

    assert candidate["agent_intent"] == "I will retry"
    assert candidate["asked"].startswith("fix it, my ")
    assert SECRET.split("=")[1] not in str(candidate)
    assert candidate["times_it_happened"] == 1 and candidate["sessions_it_happened_in"] == 1
    assert candidate["outcome"]


def test_the_candidate_counts_every_stored_lesson_of_the_same_trouble():
    (lesson,) = asked_lessons()
    other = replace(lesson, pain_point=replace(lesson.pain_point, session_id="s2"))

    candidate = review_candidate(lesson, None, [lesson, other])

    assert candidate["times_it_happened"] == 2 and candidate["sessions_it_happened_in"] == 2


def test_an_unfixed_candidate_says_the_history_shows_no_fix():
    (lesson,) = asked_lessons()
    unfixed = replace(lesson, resolution=(), changed_alongside=())

    assert review_candidate(unfixed, None)["outcome"] == "The history shows no fix."


def test_a_fixed_candidate_names_the_fix_in_its_outcome():
    (lesson,) = asked_lessons()
    fixed = replace(lesson, resolution=("ran `pip install pyyaml`",))

    assert review_candidate(fixed, None)["outcome"] == "It was fixed: ran `pip install pyyaml`."
