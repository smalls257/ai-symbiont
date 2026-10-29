"""PLUG-AGENT-1 harness pieces on hand-written lessons, failures and configs."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"


@pytest.fixture
def mods(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    import lessons
    import plug_agent_notes
    import plug_agent_store

    yield {"lessons": lessons, "notes": plug_agent_notes, "store": plug_agent_store}
    for name in ("plug_agent_notes", "plug_agent_store"):
        sys.modules.pop(name, None)


def lesson(
    mods, lesson_id, repo="o/r", program="python", error_class="ImportError", failed="python a.py"
):
    return mods["lessons"].Lesson(
        lesson_id, repo, program, "a.py", failed, f"{error_class}: x", error_class,
        "python -m a", ("-m",),
    )  # fmt: skip


def test_store_keeps_only_earlier_instances_of_unscored_repos(mods):
    by_repo = {
        "o/r": [
            lesson(mods, "own"),
            lesson(mods, "early"),
            lesson(mods, "late"),
            lesson(mods, "nodate"),
        ],
        "s/scored": [lesson(mods, "sc", repo="s/scored")],
        "x/other": [lesson(mods, f"x{n}", repo="x/other") for n in range(100)],
    }
    instance_of = {"own": "t", "early": "e", "late": "l", "nodate": "u", "sc": "e"}
    instance_of |= {f"x{n}": "e" for n in range(100)}
    dates = {"t": "2024-02", "e": "2024-01", "l": "2024-03", "u": None}
    task = {"instance_id": "t", "repo": "o/r", "created_at": "2024-02"}
    store = mods["store"].store_for(task, by_repo, instance_of, dates, frozenset({"s/scored"}))
    ids = [item.lesson_id for item in store.candidates]
    assert ids[0] == "early" and "own" not in ids and "late" not in ids and "nodate" not in ids
    assert len(ids) == mods["store"].PROMPT_LESSONS
    assert (
        store.removed_scored_repo,
        store.removed_own_instance,
        store.removed_later_or_undated,
    ) == (1, 1, 2)
    again = mods["store"].store_for(task, by_repo, instance_of, dates, frozenset({"s/scored"}))
    assert again.candidates == store.candidates  # seeded by the instance id


def test_failure_needs_a_failed_command_naming_an_error(mods):
    notes = mods["notes"]
    assert notes.failure_of("python a.py", 0, "ImportError: x") is None
    assert notes.failure_of("ls", 1, "nothing here") is None
    found = notes.failure_of(
        "cd /workspace/r && python a.py", 1, "Traceback\nImportError: no module x"
    )
    assert found.failed == "python a.py" and found.key() == ("ImportError", "python")
    assert found.situation("o/r").startswith("Ran `python a.py` in o/r")


def test_each_arm_picks_its_note_once_per_failure(mods):
    notes = mods["notes"]
    store = [
        lesson(mods, "a"),
        lesson(mods, "b", program="pip", error_class="OSError", failed="pip x"),
    ]
    failure = notes.failure_of("python a.py", 1, "ImportError: x")
    rag = notes.NoteSource(notes.NoteArm.RAG, "o/r", store, 0.0, 0.5)
    assert rag.note_for(1, failure).count("\n") == 1  # two lessons in the store, top 3 asked
    assert rag.note_for(2, failure) is None  # the same failure again: nothing new
    assert notes.NoteSource(notes.NoteArm.NONE, "o/r", store, 0.0, 0.5).note_for(1, failure) is None
    ranker = notes.NoteSource(notes.NoteArm.RANKER, "o/r", store, 1e9, 0.5)
    assert ranker.note_for(1, failure) is None and ranker.events[0]["lessons"] == []
    judged = notes.NoteSource(
        notes.NoteArm.JUDGE, "o/r", store, 0.0, 0.5, judge=lambda pairs: [0.9, 0.1]
    )
    assert "`python a.py` failed" in judged.note_for(1, failure)
    assert judged.events[0]["top"] == 0.9
    assert notes.known_mistake(failure, store)


def test_a_judge_that_does_not_answer_stops_the_run(mods, monkeypatch):
    notes = mods["notes"]

    def refused(*args, **kwargs):
        raise ConnectionRefusedError("down")

    monkeypatch.setattr(notes.urllib.request, "urlopen", refused)
    store = [lesson(mods, "a")]
    failure = notes.failure_of("python a.py", 1, "ImportError: x")
    with pytest.raises(notes.JudgeDownError):
        notes.NoteSource(notes.NoteArm.JUDGE, "o/r", store, 0.0, 0.5).note_for(1, failure)
    down = notes.judge_client("http://127.0.0.1:9/score")
    with pytest.raises(notes.JudgeDownError):
        down([{"system": "s", "prompt": "p"}])
    with pytest.raises(ValueError, match="loopback"):
        notes.judge_client("http://example.com/score")


def test_runner_refuses_drafts_and_unpinned_configs(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROUTEA))
    for name in ("minisweagent", "minisweagent.agents", "minisweagent.agents.default",
                 "minisweagent.environments", "minisweagent.environments.docker",
                 "plug_agent_env"):  # fmt: skip
        monkeypatch.setitem(sys.modules, name, type(sys)("stub"))
    sys.modules["plug_agent_env"].run_task = None
    import plug_agent_run as runner

    config = tmp_path / "c.json"
    config.write_text(json.dumps({"a": 1}))
    digest = hashlib.sha256(config.read_bytes()).hexdigest()
    draft = tmp_path / "x-DRAFT.md"
    draft.write_text(f"config sha256: {digest}")
    with pytest.raises(SystemExit, match="draft"):
        runner.checked_config(draft, config, runner.Mode.LIVE)
    frozen = tmp_path / "x.md"
    frozen.write_text("config sha256: " + "0" * 64)
    with pytest.raises(SystemExit, match="not the prereg"):
        runner.checked_config(frozen, config, runner.Mode.LIVE)
    frozen.write_text(f"config sha256: `{digest}`")
    assert runner.checked_config(frozen, config, runner.Mode.LIVE) == {"a": 1}
    config.write_text(json.dumps({"a": ""}))
    with pytest.raises(SystemExit, match="blank"):
        runner.checked_config(draft, config, runner.Mode.DRY)
    assert runner.order_key("t") == hashlib.sha256(b"plug-agent-1:t").hexdigest()
    sys.modules.pop("plug_agent_run", None)


def stub_modules(monkeypatch, names):
    for name in names:
        monkeypatch.setitem(sys.modules, name, type(sys)("stub"))


def test_the_wrapper_counts_failures_and_appends_the_arms_note(mods, monkeypatch):
    stub_modules(monkeypatch, ("minisweagent", "minisweagent.agents", "minisweagent.agents.default",
                               "minisweagent.environments", "minisweagent.environments.docker",
                               "run_calibration", "taskenv", "teacher_model"))  # fmt: skip
    sys.modules["minisweagent.agents.default"].DefaultAgent = None
    sys.modules["minisweagent.environments.docker"].DockerEnvironment = None
    for name in ("Setting", "agent_config", "agent_model", "classify", "token_counts"):
        setattr(sys.modules["run_calibration"], name, None)
    sys.modules["taskenv"].TaskEnvError, sys.modules["taskenv"].grade = Exception, None
    sys.modules["taskenv"].install_script = None
    sys.modules["taskenv"].history_scrub_script = None
    sys.modules["teacher_model"].Teacher, sys.modules["teacher_model"].teacher_model = None, None
    import plug_agent_env as env_module

    class Inner:
        def execute(self, action, cwd="", *, timeout=None):
            failing = action["command"].startswith("python")
            return {"output": "ImportError: x" if failing else "ok", "returncode": int(failing)}

        def serialize(self):
            return {"info": {"config": {}}}

    notes = mods["notes"]
    source = notes.NoteSource(notes.NoteArm.RAG, "o/r", [lesson(mods, "a")], 0.0, 0.5)
    log = env_module.RunLog()
    wrapped = env_module.LocalNotedEnvironment(Inner(), source, log)
    assert wrapped.execute({"command": "ls"})["output"] == "ok"
    out = wrapped.execute({"command": "python a.py"})["output"]
    assert "[symbiont]" in out and "failed with ImportError" in out
    assert log.failure_keys == [["ImportError", "python"]] and log.known_mistakes == 1
    assert wrapped.serialize()["info"]["config"]["symbiont_wrap"] == {"arm": "rag"}
    sys.modules.pop("plug_agent_env", None)


def test_task_check_lists_every_drop_with_its_reason(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    stub_modules(monkeypatch, ("taskenv",))

    class Graded:
        def __init__(self, resolved):
            self.resolved = resolved

    outcomes = {("g", "gold"): True, ("g", ""): False, ("e", "gold"): True, ("e", ""): True,
                ("b", "gold"): False}  # fmt: skip
    sys.modules["taskenv"].TaskEnvError = RuntimeError
    sys.modules["taskenv"].grade = lambda image, row, patch, prepare: Graded(
        outcomes[(row["instance_id"], patch)]
    )
    import plug_agent_tasks as tasks

    rows = {i: {"instance_id": i, "docker_image": "img", "patch": "gold"} for i in "geb"}
    assert tasks.check(rows["g"]) == ("g", None)
    assert tasks.check(rows["e"])[1] == str(tasks.Drop.EMPTY_PASSES)
    assert tasks.check(rows["b"])[1] == str(tasks.Drop.GOLD_FAILS)
    assert tasks.check({"instance_id": "n", "docker_image": None})[1] == str(tasks.Drop.NO_IMAGE)
    sys.modules.pop("plug_agent_tasks", None)


def test_the_judge_server_averages_p_yes_over_its_adapters(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    stub_modules(
        monkeypatch, ("torch", "peft", "transformers", "score_pairs_torch", "train_lora_torch")
    )
    sys.modules["peft"].PeftModel = None
    sys.modules["transformers"].AutoModelForCausalLM = sys.modules["transformers"].AutoTokenizer = (
        None
    )
    sys.modules["train_lora_torch"].DEVICE = "cpu"
    scores = {"s0": [0.2, 0.8], "s1": [0.4, 0.6]}
    pairs_module = sys.modules["score_pairs_torch"]
    pairs_module.BATCH, pairs_module.single_token = 16, None
    pairs_module.prompt_of = lambda tokenizer, row: [len(row["text"])]
    pairs_module.yes_probability = lambda m, t, chunk, yes, no: scores[m.active][: len(chunk)]
    import plug_judge_server as server

    class Model:
        active = "s0"

        def set_adapter(self, name):
            self.active = name

    model = Model()
    judge = object.__new__(server.Judge)
    judge.tokenizer, judge.yes, judge.no, judge.names, judge.model = None, 1, 2, ["s0", "s1"], model
    assert judge.score(
        [{"system": "s", "prompt": "a"}, {"system": "s", "prompt": "b"}]
    ) == pytest.approx([0.3, 0.7])
    sys.modules.pop("plug_judge_server", None)


def test_row_fetch_refuses_missing_ids_and_dates_keep_undated(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    stub_modules(monkeypatch, ("duckdb",))

    class Cursor:
        description = [("instance_id",), ("created_at",)]

        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Connection:
        def sql(self, text):
            return None

        def execute(self, query, ids):
            return Cursor([("a", "2024")])

    sys.modules["duckdb"].connect = Connection
    import plug_agent_rows as rows

    assert rows.fetch_dates(["a", "b"]) == {"a": "2024", "b": None}
    with pytest.raises(LookupError, match="not in SWE-rebench"):
        rows.fetch(["a", "b"])
    sys.modules.pop("plug_agent_rows", None)


def test_task_check_resumes_from_its_progress_log(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROUTEA))
    stub_modules(monkeypatch, ("taskenv",))
    sys.modules["taskenv"].TaskEnvError = RuntimeError
    sys.modules["taskenv"].grade = None
    import plug_agent_tasks as tasks

    log = tmp_path / "t.progress.jsonl"
    log.write_text(json.dumps({"id": "a", "drop": None}) + "\n")
    rows = [{"instance_id": "a"}, {"instance_id": "b", "docker_image": None}]
    assert tasks.checked(rows, log, 1) == {"a": None, "b": str(tasks.Drop.NO_IMAGE)}
    assert len(log.read_text().splitlines()) == 2
    sys.modules.pop("plug_agent_tasks", None)
