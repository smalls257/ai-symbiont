"""A rule pinned to a file reaches the agent when it reads or edits that file.

Violation guarded against: Paper Tiger. The D3 experiment stored a file-scoped review ruling that
passed every test and was delivered 0 times, because the gate only looked at prompts and failures.
The hook inputs below are synthetic but shaped like Muse Code's: `read_file` carries
{path, offset, limit}, `edit_file` carries {path, find, replace}, and `path` is relative to the
working directory (the model sometimes sends an absolute path instead).
"""

import json

import pytest

from symbiont.core.counters import Counters
from symbiont.core.rule_relevance import file_scoped_rules, rules_of
from symbiont.delivery import hooks
from symbiont.delivery.hooks import HookEvent
from symbiont.miner.lesson_context import AppliesTo, AuthoredLesson, LessonKind
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.onboarding import Lookups
from symbiont.service.repo_gate import RepoGate
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery

PROJECT = "sqlglot"
CWD = "/work/runs/trial-1/sqlglot"
PR = "https://github.com/acme/sqlglot/pull/7396"
COPY_RULING = (
    "Do not copy properties inside a DuckDB generator sub-method; "
    "the top-level generate method already handles copying."
)
GENERATOR = "sqlglot/generators/duckdb.py"
DIALECT = "sqlglot/dialects/duckdb.py"


def ruling(ident="w-copy", files=(GENERATOR,), **extra):
    return AuthoredLesson(
        ident, COPY_RULING, LessonKind.RULE, files, "from PR #7396 review", source_url=PR, **extra
    )


class Rig:
    def __init__(self, tmp_path, lessons):
        registry = RepoRegistry(tmp_path)
        registry.record_stance(PROJECT, RepoStance.GIVEN)
        self.events = EventLog(tmp_path / "runs" / "20261103T000000Z", "counters")
        gate = RepoGate(registry, None, Lookups(written=lambda project: lessons))
        parts = ServiceParts(
            Store.open(tmp_path / "s.db"),
            Counters(),
            self.events,
            ServiceMode.WARN_AND_RECALL,
            gate=gate,
        )
        self.service = Service(parts)

    def tool(self, event, name, tool_input, session_id="s1", response="ok"):
        data = {
            "hook_event_name": event.value,
            "session_id": session_id,
            "cwd": CWD,
            "tool_name": name,
            "tool_input": tool_input,
            "tool_response": response,
        }
        body = hooks.observe_body(event, data, "muse_code", PROJECT)
        reply = self.service.respond("/observe", body)
        assert reply.status == 200, reply.body
        return reply.body["notes"]

    def read(self, path, session_id="s1"):
        shape = {"path": path, "offset": 1, "limit": 60}
        return self.tool(HookEvent.POST_TOOL_USE, "read_file", shape, session_id)

    def edit(self, path, session_id="s1"):
        shape = {"path": path, "find": "a.copy()", "replace": "a"}
        return self.tool(HookEvent.POST_TOOL_USE, "edit_file", shape, session_id)

    def fired_by(self):
        lines = self.events.path.read_text().splitlines()
        return [e["fired_by"] for e in map(json.loads, lines) if e.get("fired_by")]


def test_a_successful_read_of_the_rules_file_delivers_it_before_any_edit(tmp_path):
    rig = Rig(tmp_path, [ruling()])

    notes = rig.read(GENERATOR)

    assert notes == [f"[symbiont] In this repo: {COPY_RULING.rstrip('.')}."]
    assert rig.fired_by() == [f"rule: file: {GENERATOR} (+4)"]


def test_an_edit_of_the_rules_file_delivers_it_as_a_backstop(tmp_path):
    rig = Rig(tmp_path, [ruling()])

    assert len(rig.edit(GENERATOR)) == 1


def test_an_absolute_path_from_the_tool_is_the_same_file(tmp_path):
    rig = Rig(tmp_path, [ruling()])

    assert len(rig.read(f"{CWD}/{GENERATOR}")) == 1


def test_the_rule_is_said_once_per_session_across_a_read_and_an_edit(tmp_path):
    rig = Rig(tmp_path, [ruling()])

    assert len(rig.read(GENERATOR)) == 1
    assert rig.edit(GENERATOR) == []
    assert rig.read(GENERATOR) == []
    assert len(rig.read(GENERATOR, session_id="next")) == 1


def test_a_sibling_file_with_the_same_name_does_not_fire_a_file_scoped_rule(tmp_path):
    rig = Rig(tmp_path, [ruling()])

    assert rig.read(DIALECT) == []
    assert rig.read("sqlglot/generators/postgres.py") == []


def test_words_alone_never_fire_on_a_read(tmp_path):
    tagged = ruling(files=(), applies=AppliesTo(terms=("copy",), areas=()))
    rig = Rig(tmp_path, [tagged])

    assert rig.read("docs/copy.md") == []


def test_a_ruling_pinned_to_two_files_fires_for_either(tmp_path):
    rig = Rig(tmp_path, [ruling(files=(GENERATOR, DIALECT))])

    assert len(rig.read(DIALECT)) == 1


def test_the_matcher_takes_whole_trailing_path_parts_only():
    items = rules_of([], {}, [ruling(files=("generators/duckdb.py",))])

    assert file_scoped_rules([f"{CWD}/{GENERATOR}"], items)
    assert not file_scoped_rules(["sqlglot/mygenerators/duckdb.py"], items)
    assert file_scoped_rules([".\\sqlglot\\generators\\duckdb.py"], items)


def test_a_pr_ruling_is_a_house_rule_at_the_first_prompt(tmp_path):
    rig = Rig(tmp_path, [ruling()])
    data = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s1",
        "cwd": CWD,
        "prompt": "Fix Y",
    }
    body = hooks.observe_body(HookEvent.USER_PROMPT_SUBMIT, data, "muse_code", PROJECT)

    notes = rig.service.respond("/observe", body).body["notes"]

    assert notes[0].startswith("[symbiont] House rules for this repo (from your corrections and PR")
    assert COPY_RULING in notes[0]
