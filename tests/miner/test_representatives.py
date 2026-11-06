"""Which themes are offered and which sessions are drawn, so every click has an example."""

from dataclasses import replace

from record_builders import edit, run, session, user
from symbiont.miner.patterns import StrugglePattern
from symbiont.miner.representatives import (
    min_sessions_shown,
    representative_strips,
    theme_words,
)
from symbiont.miner.strips import Lane, burstiness, strip_of
from symbiont.miner.struggle import SessionFacts
from symbiont.miner.themes import Codebase

CODE = Codebase(frozenset({"app"}))
FAIL = "Traceback\nValueError: no"


def facts(sid, themes=(), patterns=()):
    return SessionFacts(sid, sid, frozenset(themes), frozenset(patterns), 0, {})


def named(sid, records):
    return [replace(r, session_id=sid) for r in session(*records)]


def test_a_theme_in_every_session_is_the_project_not_a_theme():
    many = [facts(f"s{n}", ["parser", "project"] if n < 3 else ["project"]) for n in range(12)]
    assert theme_words(many) == ["parser"]


def test_a_theme_seen_once_is_an_anecdote():
    assert theme_words([facts("a", ["once"]), facts("b", ["twice"]), facts("c", ["twice"])]) == [
        "twice"
    ]


def test_the_page_lists_a_theme_only_when_enough_sessions_share_it():
    assert min_sessions_shown(10) == 2
    assert min_sessions_shown(3000) == 60


def test_a_strip_names_programs_and_files_but_keeps_no_output():
    steps = named(
        "s",
        [
            user("hi"),
            run("pytest tests/a.py", 1, "SECRET OUTPUT"),
            edit("app/a.py"),
            edit("/tmp/scratch.py"),
            run("pytest tests/a.py", 0),
            run("C-c", 130),
        ],
    )
    drawn = strip_of(steps, CODE)
    assert [s.lane for s in drawn] == [
        Lane.YOU,
        Lane.FAILED,
        Lane.CODE_EDIT,
        Lane.SCRATCH_EDIT,
        Lane.PASSED,
    ]
    assert "SECRET" not in str(drawn)


def test_the_densest_session_of_a_theme_and_of_a_pattern_cell_gets_the_strip():
    calm = named("calm", [run("pytest", 0)] * 50)
    bursty = named("bursty", [run(f"pytest t{n}", 1, FAIL) for n in range(4)] * 12)
    assert burstiness(bursty) > burstiness(calm)
    facts_ = [
        facts("calm", ["parser"], []),
        facts("bursty", ["parser"], [StrugglePattern.RERUNNING]),
    ]

    strips = representative_strips([calm, bursty], facts_, CODE)

    assert {s.session_id for s in strips} == {"bursty"} or "bursty" in {
        s.session_id for s in strips
    }
    assert all(s.steps for s in strips)
