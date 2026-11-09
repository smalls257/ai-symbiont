"""Written lessons (reflection, onboarding, symbiont_add_lessons) are lessons like any other.

Failures guarded against: a Silent Fallback (`symbiont lessons` saying "no stored lessons" while
two reflection lessons exist) and a Leaky Narrative at the id (an id the listing prints that the
context route, `forget` and the dashboard then refuse as "no lesson").
"""

from dataclasses import replace
from datetime import date

import pytest

from record_builders import edit, run, session
from store_builders import save_lessons
from symbiont import cli
from symbiont.core.rule_relevance import rules_of
from symbiont.miner.lesson_context import (
    AuthoredLesson,
    LessonContext,
    LessonKind,
    Priority,
    ReviewOverride,
    Severity,
)
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.trained import lesson_id
from symbiont.service.app import ServiceMode
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
from symbiont.service.effective_context import effective_contexts
from symbiont.service.wiring import open_service
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery
IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"
REFLECTED = AuthoredLesson(
    "w-reflect000001",
    "Keep parser imports lazy.",
    LessonKind.RULE,
    ("app/parser.py",),
    "from reflection",
)
ADDED = AuthoredLesson(
    "w-added0000002",
    "Money is integer cents.",
    LessonKind.MISTAKE,
    (),
    "from the developer",
    Severity.HIGH,
)


def command(*words, data_dir):
    return cli.main([*words, "--project", "demo", "--data-dir", str(data_dir)])


def mined(store):
    steps = session(
        run("pytest tests/test_parser.py", 1, IMPORT),
        edit("app/parser.py", diff="-a\n+def parse(text):\n"),
        run("pytest tests/test_parser.py", 0, "1 passed"),
    )
    records = [replace(r, project="demo") for r in steps]
    lessons = lessons_from(mine_history(sessions_of(records), {}), records, frozenset())
    save_lessons(store, "demo", [], lessons, held_out_tasks=frozenset())
    return lessons


@pytest.fixture
def store(tmp_path):
    return Store.open(tmp_path / "store.db")


def test_lessons_lists_written_lessons_with_their_source_when_nothing_was_mined(
    tmp_path, store, capsys
):
    store.curation.add_authored("demo", REFLECTED)
    store.curation.add_authored("demo", ADDED)

    assert command("lessons", data_dir=tmp_path) == 0

    out = capsys.readouterr().out
    assert "no stored lessons" not in out
    assert "w-reflect000001  reflection  Keep parser imports lazy." in out
    assert "w-added0000002  added" in out and "Money is integer cents." in out


def test_lessons_lists_mined_and_written_together(tmp_path, store, capsys):
    lessons = mined(store)
    store.curation.add_authored("demo", REFLECTED)

    command("lessons", data_dir=tmp_path)

    out = capsys.readouterr().out
    assert f"{lesson_id(lessons[0])}  mined" in out and "w-reflect000001  reflection" in out


def test_a_dismissed_lesson_is_hidden_until_all_is_asked_for(tmp_path, store, capsys):
    store.curation.add_authored("demo", REFLECTED)
    store.curation.add_authored("demo", ADDED)
    store.contexts.save("w-added0000002", "demo", LessonContext("", intentional=True))

    command("lessons", data_dir=tmp_path)
    plain = capsys.readouterr().out
    command("lessons", "--all", data_dir=tmp_path)
    everything = capsys.readouterr().out

    assert "w-added0000002" not in plain and "1 dismissed lesson(s) hidden" in plain
    assert "w-reflect000001" in plain
    assert "w-added0000002" in everything and "[dismissed]" in everything


def test_the_context_route_stores_words_priority_and_a_dismissal_for_a_written_lesson(
    tmp_path, store
):
    store.curation.add_authored("demo", REFLECTED)
    service = open_service(tmp_path, ServiceMode.WARN_AND_RECALL)
    path = "/lessons/w-reflect000001/context"

    saved = service.respond(path, {"text": "Also in cli.py.", "priority": "high"})
    dismissed = service.respond(
        path, {"text": "Also in cli.py.", "intentional": True, "review_override": "dismiss"}
    )
    unknown = service.respond("/lessons/w-nothing/context", {"text": "x"})
    other_repo = service.respond(path, {"text": "x", "project": "elsewhere"})

    assert saved.status == 200 and saved.body == {"lesson": "w-reflect000001", "project": "demo"}
    assert dismissed.status == 200
    assert unknown.status == 404 and other_repo.status == 404
    reread = Store.open(tmp_path / "store.db")
    assert reread.contexts.get("w-reflect000001").intentional is True
    assert reread.contexts.overrides("demo") == {"w-reflect000001": ReviewOverride.DISMISS}


def test_the_dashboard_shows_the_words_priority_and_silence_of_a_written_lesson(store):
    store.curation.add_authored("demo", REFLECTED)
    store.contexts.save(
        "w-reflect000001", "demo", LessonContext("Also in cli.py.", True, Priority.HIGH)
    )
    view = RepoView(
        "demo", [], effective_contexts(store, "demo"), {}, written=store.curation.authored("demo")
    )

    (lesson,) = dashboard_snapshot(view, date(2026, 11, 2))["lessons"]

    assert lesson["id"] == "w-reflect000001"
    assert (lesson["context"], lesson["intentional"], lesson["priority"]) == (
        "Also in cli.py.",
        True,
        "high",
    )


def test_forget_deletes_a_written_lesson_and_its_words_and_leaves_the_others(
    tmp_path, store, capsys
):
    store.curation.add_authored("demo", REFLECTED)
    store.curation.add_authored("demo", ADDED)
    store.contexts.save("w-reflect000001", "demo", LessonContext("Also in cli.py."))

    assert command("forget", "--lesson", "w-reflect000001", data_dir=tmp_path) == 0

    assert "forgot the written lesson w-reflect000001" in capsys.readouterr().out
    reread = Store.open(tmp_path / "store.db")
    assert [item.ident for item in reread.curation.authored("demo")] == ["w-added0000002"]
    assert reread.contexts.get("w-reflect000001") is None


def test_forget_of_a_lesson_nobody_has_is_still_an_error(tmp_path, store, capsys):
    store.curation.add_authored("demo", REFLECTED)

    assert command("forget", "--lesson", "w-nothing", data_dir=tmp_path) == 1
    assert "no lesson w-nothing" in capsys.readouterr().err
    assert (
        cli.main(
            [
                "forget",
                "--lesson",
                "w-reflect000001",
                "--project",
                "elsewhere",
                "--data-dir",
                str(tmp_path),
            ]
        )
        == 1
    )


def test_context_add_works_for_a_written_lesson_by_id_and_as_last(tmp_path, store, capsys):
    store.curation.add_authored("demo", REFLECTED)

    assert command("context", "add", "last", "Applies to cli.py too.", data_dir=tmp_path) == 0

    assert "saved for w-reflect000001 (written lesson: Keep parser imports lazy.)" in (
        capsys.readouterr().out
    )
    assert store.contexts.get("w-reflect000001").text == "Applies to cli.py too."


def test_a_dismissed_written_lesson_makes_no_rule_and_the_words_join_the_rule_otherwise():
    silent = {"w-added0000002": LessonContext("", intentional=True)}
    spoken = {"w-reflect000001": LessonContext("Also in cli.py.", priority=Priority.HIGH)}

    assert [r.ident for r in rules_of([], silent, [REFLECTED, ADDED])] == ["w-reflect000001"]
    (rule,) = rules_of([], spoken, [REFLECTED])
    assert rule.words.text == "Keep parser imports lazy. Also in cli.py"
    assert rule.words.priority is Priority.HIGH


def test_a_dismiss_or_keep_answer_counts_for_a_lesson_nobody_reviewed(store):
    store.curation.add_authored("demo", REFLECTED)
    store.contexts.save_override("w-reflect000001", "demo", ReviewOverride.DISMISS)
    assert effective_contexts(store, "demo")["w-reflect000001"].intentional is True

    store.contexts.save_override("w-reflect000001", "demo", ReviewOverride.KEEP)
    assert effective_contexts(store, "demo")["w-reflect000001"].intentional is False
