"""The commands behind `/symbiont`: answer for a repository, see, silence, forget.

Failure guarded against: a Black Box in the developer's hands ("why did that note fire?" with no
answer) and a Silent Fallback (mining a repository nobody said yes to).
"""

import json
import re
import threading
from dataclasses import replace

import pytest

from record_builders import edit, run, session
from symbiont import cli
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.service import server
from symbiont.service.app import ServiceMode
from symbiont.service.events import Call, EventLog
from symbiont.service.wiring import Guards, open_service
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery

IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"


def command(*words, data_dir):
    return cli.main([*words, "--project", "demo", "--data-dir", str(data_dir)])


def mined_store(data_dir):
    steps = session(
        run("pytest tests/test_parser.py", 1, IMPORT),
        edit("app/parser.py", diff="-a\n+def parse(text):\n"),
        run("pytest tests/test_parser.py", 0, "1 passed"),
    )
    records = [replace(r, project="demo") for r in steps]
    lessons = lessons_from(mine_history(sessions_of(records), {}), records)
    data_dir.mkdir(parents=True, exist_ok=True)
    store = Store.open(data_dir / "store.db")
    store.save_mining("demo", [], lessons, held_out_tasks=frozenset())
    return store, lessons


def log_a_note(data_dir, lessons):
    events = EventLog(data_dir / "runs" / "20261102T000000Z", "counters")
    pain = lessons[0].pain_point
    events.append(
        Call("observe", "PostToolUseFailure", "demo"),
        pain.signature,
        list(pain.record_refs),
        ["Last time, x."],
    )


def test_allow_decline_show_and_reset_are_remembered_per_repository(tmp_path, capsys):
    assert command("repo", "show", data_dir=tmp_path) == 0
    assert "not asked yet" in capsys.readouterr().out

    command("repo", "allow", data_dir=tmp_path)
    assert "stays on this computer" in capsys.readouterr().out
    assert RepoRegistry(tmp_path).stance("demo") is RepoStance.GIVEN

    command("repo", "decline", data_dir=tmp_path)
    assert "stays off" in capsys.readouterr().out

    command("repo", "reset", data_dir=tmp_path)
    assert RepoRegistry(tmp_path).stance("demo") is None


def test_mining_past_sessions_is_refused_until_the_developer_said_yes(tmp_path, capsys):
    assert command("repo", "mine", data_dir=tmp_path) == 1
    assert "repo allow" in capsys.readouterr().err
    assert not (tmp_path / "store.db").exists(), "nothing is stored without a yes"


def test_mining_reads_the_claude_code_sessions_of_the_repository(tmp_path, monkeypatch, capsys):
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    folder = home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))
    folder.mkdir(parents=True)
    (folder / "one.jsonl").write_text(claude_log())
    monkeypatch.setenv("HOME", str(home))
    command("repo", "allow", data_dir=tmp_path / "data")
    capsys.readouterr()

    assert command("repo", "mine", "--repo-dir", str(repo), data_dir=tmp_path / "data") == 0

    assert (
        "learned 1 lessons from 1 claude-code sessions, 0 muse-code sessions"
        in capsys.readouterr().out
    )
    assert len(Store.open(tmp_path / "data" / "store.db").lessons("demo")) == 1


def test_a_repository_with_no_sessions_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    command("repo", "allow", data_dir=tmp_path)
    capsys.readouterr()

    assert command("repo", "mine", "--repo-dir", str(tmp_path), data_dir=tmp_path) == 0
    assert "no Claude Code or Muse Code sessions found" in capsys.readouterr().out


def test_why_explains_the_last_note_from_the_event_log(tmp_path, capsys):
    _, lessons = mined_store(tmp_path)
    log_a_note(tmp_path, lessons)

    assert command("why", data_dir=tmp_path) == 0

    out = capsys.readouterr().out
    assert "Last time, x." in out
    assert "`pytest tests/test_parser.py` failed with ImportError" in out
    assert "rests on 1 earlier record" in out


def test_why_with_no_note_says_so(tmp_path, capsys):
    assert command("why", data_dir=tmp_path) == 0
    assert "no note has been shown for demo yet" in capsys.readouterr().out


def test_mute_silences_the_last_notes_kind_of_trouble(tmp_path, capsys):
    _, lessons = mined_store(tmp_path)
    log_a_note(tmp_path, lessons)

    assert command("mute", data_dir=tmp_path) == 0

    signature = lessons[0].pain_point.signature
    assert (signature.signal.value, *signature.key) in RepoRegistry(tmp_path).muted("demo")


def test_forget_deletes_the_lessons_and_keeps_them_silenced(tmp_path, capsys):
    store, lessons = mined_store(tmp_path)
    log_a_note(tmp_path, lessons)

    assert command("forget", data_dir=tmp_path) == 0

    assert store.lessons("demo") == []
    assert RepoRegistry(tmp_path).muted("demo")
    assert "forgot 1 lesson(s)" in capsys.readouterr().out


def test_lessons_lists_ids_and_forget_takes_one(tmp_path, capsys):
    store, lessons = mined_store(tmp_path)
    command("lessons", data_dir=tmp_path)
    (line,) = capsys.readouterr().out.splitlines()
    lesson_id = line.split()[0]

    assert command("forget", "--lesson", lesson_id, data_dir=tmp_path) == 0
    assert store.lessons("demo") == []
    assert command("forget", "--lesson", "nope", data_dir=tmp_path) == 1


def test_mute_with_no_note_to_act_on_fails_loudly(tmp_path, capsys):
    assert command("mute", data_dir=tmp_path) == 1
    assert "names no kind of trouble" in capsys.readouterr().err


def test_status_asks_the_service_and_reports_offline_when_it_is_down(tmp_path, capsys):
    registry = RepoRegistry(tmp_path)
    registry.record_stance("demo", RepoStance.GIVEN)
    service = open_service(tmp_path, ServiceMode.WARN_AND_RECALL, guards=Guards(repos=registry))
    httpd = server.bind(service, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        command("status", "--port", str(httpd.server_address[1]), data_dir=tmp_path)
        up = capsys.readouterr().out
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert "symbiont is running. demo: on; 0 stored lessons" in up
    command("status", "--port", "1", data_dir=tmp_path)
    assert capsys.readouterr().out.startswith("symbiont offline:")


def claude_log():
    """Claude Code JSONL for the three steps: a failing Bash call, an edit, a passing call."""

    def call(id_, name, arguments):
        return {
            "type": "assistant",
            "sessionId": "s1",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": id_, "name": name, "input": arguments}],
            },
        }

    def result(id_, text, error=False):
        return {
            "type": "user",
            "sessionId": "s1",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": id_, "content": text, "is_error": error}
                ],
            },
        }

    events = [
        call("a", "Bash", {"command": "pytest tests/test_parser.py"}),
        result("a", "Exit code 1\n" + IMPORT, error=True),
        call(
            "b",
            "Edit",
            {"file_path": "app/parser.py", "old_string": "a", "new_string": "def parse(text):"},
        ),
        result("b", "ok"),
        call("c", "Bash", {"command": "pytest tests/test_parser.py"}),
        result("c", "1 passed"),
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


def muse_line(payload_type, payload):
    stream = {"kind": "session", "id": "m1"}
    return json.dumps({"stream": stream, "payload_type": payload_type, "payload": payload})


def muse_run(event):
    return muse_line("runtime.session", {"kind": "run", "event": event})


def muse_shell(call_id, command, text, exit_code):
    call = {"name": "bash", "call_id": call_id, "args": {"cmd": command}}
    result = {"call_id": call_id, "text": text, "exit_code": exit_code}
    return [
        muse_run({"kind": "assistant_tool_calls_committed", "tool_calls": [call]}),
        muse_run({"kind": "tool_result_batch_committed", "results": [result]}),
    ]


def muse_edit(call_id, path, patch):
    call = {"name": "edit_file", "call_id": call_id, "args": {"path": path, "patch": patch}}
    result = {"call_id": call_id, "text": "ok"}
    return [
        muse_run({"kind": "assistant_tool_calls_committed", "tool_calls": [call]}),
        muse_run({"kind": "tool_result_batch_committed", "results": [result]}),
    ]


def muse_log(repo):
    metadata = muse_line(
        "runtime.session.metadata", {"record": {"workspace_root": str(repo.resolve())}}
    )
    command = "pytest tests/test_parser.py"
    lines = [
        metadata,
        *muse_shell("a", command, "Exit code 1\n" + IMPORT, 1),
        *muse_edit("b", "app/parser.py", "-a\n+def parse(text):\n"),
        *muse_shell("c", command, "1 passed", 0),
    ]
    return "\n".join(lines) + "\n"


def test_mining_reads_muse_code_sessions_of_the_repository_too(tmp_path, monkeypatch, capsys):
    repo, data_home = tmp_path / "repo", tmp_path / "xdg"
    repo.mkdir()
    log = data_home / "muse" / "sessions" / "2026" / "11" / "02" / "m1" / "session.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(muse_log(repo))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    command("repo", "allow", data_dir=tmp_path / "data")
    capsys.readouterr()

    assert command("repo", "mine", "--repo-dir", str(repo), data_dir=tmp_path / "data") == 0

    assert (
        "learned 1 lessons from 0 claude-code sessions, 1 muse-code sessions"
        in capsys.readouterr().out
    )


def test_context_add_stores_the_words_for_a_listed_lesson_and_lessons_marks_it(tmp_path, capsys):
    store, lessons = mined_store(tmp_path)
    command("lessons", data_dir=tmp_path)
    lesson_id = capsys.readouterr().out.split()[0]

    code = command(
        "context",
        "add",
        lesson_id,
        "Keep parser imports lazy.",
        "--priority",
        "high",
        data_dir=tmp_path,
    )

    words = store.contexts.get(lesson_id)
    assert code == 0 and words.text == "Keep parser imports lazy." and words.priority == "high"
    command("lessons", data_dir=tmp_path)
    assert "[your words added]" in capsys.readouterr().out


def test_context_add_last_uses_the_lesson_behind_the_last_note(tmp_path):
    store, lessons = mined_store(tmp_path)
    log_a_note(tmp_path, lessons)

    assert command("context", "add", "last", "On purpose.", "--intentional", data_dir=tmp_path) == 0

    (words,) = store.contexts.all("demo").values()
    assert words.intentional and words.text == "On purpose."


def test_context_add_for_an_unknown_lesson_fails_loudly(tmp_path, capsys):
    mined_store(tmp_path)

    assert command("context", "add", "nope:1:failed_command", "x", data_dir=tmp_path) == 1
    assert "no lesson nope:1:failed_command" in capsys.readouterr().err


def test_context_add_last_with_no_note_picks_the_newest_lesson_and_says_which(tmp_path, capsys):
    store, lessons = mined_store(tmp_path)

    assert command("context", "add", "last", "Newest.", data_dir=tmp_path) == 0

    out = capsys.readouterr().out
    assert lessons[-1].pain_point.session_id in out and "failed with ImportError" in out
    (words,) = store.contexts.all("demo").values()
    assert words.text == "Newest."


def test_context_add_last_in_a_repository_with_no_lessons_fails_loudly(tmp_path, capsys):
    assert command("context", "add", "last", "x", data_dir=tmp_path) == 1
    assert "has no stored lessons" in capsys.readouterr().err


def test_dashboard_prints_the_local_address_for_the_repository(tmp_path, capsys):
    assert command("dashboard", "--port", "7377", data_dir=tmp_path) == 0
    assert capsys.readouterr().out.strip() == "http://127.0.0.1:7377/dashboard?project=demo"


def test_settings_show_and_set_the_correction_switches(tmp_path, capsys):
    assert command("settings", "show", data_dir=tmp_path) == 0
    assert "muse_code=True" in capsys.readouterr().out

    assert command("settings", "set", "muse_code", "false", data_dir=tmp_path) == 0
    assert "muse_code=False" in capsys.readouterr().out
    assert command("settings", "set", "nope", "true", data_dir=tmp_path) == 1
    assert command("settings", "set", "muse_code", data_dir=tmp_path) == 1
