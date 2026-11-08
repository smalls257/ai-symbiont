"""Incidents: one plain-language card per mined occurrence."""

from symbiont.miner.fixes import FixKind
from symbiont.miner.incidents import (
    Incident,
    NoiseReason,
    Outcome,
    Trigger,
    TriggerKind,
    incidents_from,
    trigger_of,
)
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.resolutions import NOTHING_CHANGED, PASSED_RESPELLED
from symbiont.records.schema import Kind, Provenance, Record

PROV = Provenance("t", "x", True)


def rec(step, kind, raw="", **kw):
    return Record(
        harness="h", project="p", session_id="s1", step=step, kind=kind, raw=raw,
        provenance=PROV, **kw,
    )  # fmt: skip


def command(step, cmd, exit_code=1, raw="boom"):
    return rec(step, Kind.COMMAND, raw, command=cmd, exit_code=exit_code)


def edit(step, path):
    return rec(step, Kind.EDIT, "e", files=(path,), diff="+x\n", exit_code=0)


def user(step, text, tags=()):
    return rec(step, Kind.USER_TURN, text, tags=tags)


def failure(key, step=1, **kw):
    pain = PainPoint(Signature(Signal.FAILED_COMMAND, key), "s1", step, (("s1", step),))
    fields = dict(
        quote="q", resolution=(), unresolved_because="no later command", remote_safe=True,
        sources=(("s1", step),),
    )  # fmt: skip
    return Lesson(pain_point=pain, **{**fields, **kw})


def correction(step, text="x"):
    pain = PainPoint(Signature(Signal.CORRECTION, ("-", text)), "s1", step, (("s1", step),))
    return Lesson(
        pain_point=pain, quote=text, resolution=(), unresolved_because=None, remote_safe=True,
        sources=(("s1", step),),
    )  # fmt: skip


def cards(lessons, records=(), topics=None):
    return incidents_from(lessons, topics or {}, {"s1": list(records)})


def test_a_bad_pytest_path_reads_as_tests_that_do_not_exist():
    lesson = failure(
        ("pytest", "tests/test_app.py", "usage error or bad path"),
        resolution=("ran pytest",), fix_commands=("pytest tests/",), unresolved_because=None,
        fix=FixKind.CORRECTED_COMMAND,
    )  # fmt: skip
    (card,) = cards([lesson], [command(1, "pytest tests/test_app.py")])
    assert (
        card.what_happened == "The agent ran pytest on tests that do not exist (tests/test_app.py)."
    )
    assert card.outcome is Outcome.CORRECTED_COMMAND
    assert card.noise is None
    assert card.what_fixed_it.endswith(".")


def test_a_repro_script_fixed_by_a_codebase_edit_is_a_deliberate_repro():
    lesson = failure(
        ("python", "reproduce_issue.py", "TypeError"),
        resolution=("edited ops.py, then re-ran python",),
        unresolved_because=None, fix=FixKind.CODE_FIX, target_created=True,
        files=("pkg/ops.py",),
    )  # fmt: skip
    (card,) = cards([lesson])
    assert card.noise is NoiseReason.DELIBERATE_REPRO
    assert card.what_fixed_it == "Passed after editing ops.py."
    assert card.outcome is Outcome.FIXED_IN_CODE


def test_a_created_script_without_a_codebase_edit_is_throwaway():
    (card,) = cards([failure(("python", "reproduce_issue.py", "TypeError"), target_created=True)])
    assert card.noise is NoiseReason.THROWAWAY_SCRIPT


def test_a_failed_look_around_is_noise():
    (card,) = cards([failure(("ls", "missing/", "exit 2"))])
    assert card.noise is NoiseReason.LOOK_AROUND


def test_an_interrupt_is_noise():
    (card,) = cards([failure(("C-c", "-", "exit 1"))], [command(1, "C-c")])
    assert card.noise is NoiseReason.INTERRUPT


def test_passing_unchanged_is_a_plain_retry():
    lesson = failure(("make", "-", "exit 2"), unresolved_because=NOTHING_CHANGED)
    (card,) = cards([lesson])
    assert card.noise is NoiseReason.PLAIN_RETRY
    assert card.outcome is Outcome.PASSED_ON_RETRY
    assert card.what_fixed_it == "Nothing: it passed when run again."


def test_passing_with_other_arguments_is_never_shown_as_fixed():
    (card,) = cards([failure(("make", "-", "exit 2"), unresolved_because=PASSED_RESPELLED)])
    assert card.noise is NoiseReason.PLAIN_RETRY
    assert card.what_fixed_it.startswith("Nothing:")


def test_an_unresolved_failure_was_never_fixed():
    (card,) = cards([failure(("make", "-", "TypeError"))])
    assert card.outcome is Outcome.NEVER_FIXED
    assert card.what_fixed_it == "Never fixed in this session."
    assert card.noise is None


def test_a_real_failure_fixed_in_code_is_worth_a_look():
    lesson = failure(
        ("manage.py", "-", "OperationalError"), resolution=("edited models.py",),
        unresolved_because=None, fix=FixKind.CODE_FIX, files=("shop/models.py",),
    )  # fmt: skip
    (card,) = cards([lesson])
    assert (card.noise, card.outcome) == (None, Outcome.FIXED_IN_CODE)
    assert card.what_fixed_it == "Fixed by editing models.py."


def test_acknowledgments_are_empty_corrections():
    for text in ["ok", "yes please", "/compact", "<command-name>/clear</command-name>"]:
        (card,) = cards([correction(2, text)], [user(2, text, ("correction",))])
        assert card.noise is NoiseReason.EMPTY_CORRECTION, text


def test_a_real_correction_quotes_at_most_160_characters():
    text = "no, don't mock the database, use the fixture " + "x" * 300
    (card,) = cards([correction(2, text)], [user(2, text, ("correction",))])
    assert card.noise is None
    assert card.outcome is Outcome.DEVELOPER_STEPPED_IN
    assert card.what_happened.startswith("You corrected the agent: ")
    assert len(card.what_happened) <= len("You corrected the agent: ") + 160 + 3


def _episode_records():
    return [
        user(1, "add a test for the db"),
        edit(4, "tests/test_db.py"),
        command(5, "pytest", exit_code=0),
        user(6, "no, don't mock the database", ("correction",)),
        edit(7, "tests/conftest.py"),
    ]


def test_the_episode_starts_at_the_first_edit_the_agent_made():
    (card,) = cards([correction(6, "no, don't mock the database")], _episode_records())
    assert card.first_wrong == "The agent edited tests/test_db.py."
    assert card.cost_steps == 2
    assert card.what_fixed_it == "The agent then edited tests/conftest.py."
    assert card.situation == ("editing", "", "tests/test_db.py")


def test_nothing_after_a_correction_is_said_so():
    records = _episode_records()[:-1]
    (card,) = cards([correction(6, "no, don't mock the database")], records)
    assert card.what_fixed_it == "Nothing visible after your correction."


def test_the_episode_prefers_the_action_the_correction_names():
    records = [
        edit(2, "a/one.py"), edit(3, "src/db/models.py"),
        user(4, "you broke models.py", ("correction",)),
    ]  # fmt: skip
    (card,) = cards([correction(4, "you broke models.py")], records)
    assert card.first_wrong == "The agent edited src/db/models.py."
    assert card.cost_steps == 1


def test_without_a_named_file_the_first_failed_action_is_chosen():
    records = [
        edit(2, "a/one.py"), command(3, "make build"), edit(4, "b/two.py"),
        user(5, "that is wrong", ("correction",)),
    ]  # fmt: skip
    (card,) = cards([correction(5, "that is wrong")], records)
    assert card.first_wrong == "The agent ran `make build`, which failed."
    assert card.cost_steps == 2


def test_the_walk_back_stops_at_the_previous_developer_turn():
    records = [edit(2, "a/one.py"), user(3, "hm"), user(4, "no, wrong approach", ("correction",))]
    (card,) = cards([correction(4, "no, wrong approach")], records)
    assert (card.first_wrong, card.cost_steps) == ("", 0)
    assert card.situation == ("", "", "")


def test_the_topic_comes_from_the_session_and_defaults_to_empty():
    lesson = failure(("make", "-", "TypeError"))
    assert cards([lesson], topics={"s1": "database setup"})[0].topic == "database setup"
    assert cards([lesson], topics={"other": "x"})[0].topic == ""


def test_no_sentence_leaks_miner_internals():
    lessons = [
        failure(("pytest", "tests/a.py", "usage error or bad path")),
        failure(("make", "-", "exit 4")),
        failure(("make", "-", "<n> failed <path>"), unresolved_because=PASSED_RESPELLED),
    ]
    for card in cards(lessons):
        text = f"{card.what_happened} {card.what_fixed_it}"
        for banned in ("exit 4", "respelled", "signature", "key", "<path>"):
            assert banned not in text, text


def incident(situation):
    return Incident(
        session_id="s", step=1, signal=Signal.FAILED_COMMAND, what_happened="x.", first_wrong="",
        cost_steps=0, what_fixed_it="y.", outcome=Outcome.NEVER_FIXED, noise=None, topic="",
        files=(), situation=situation,
    )  # fmt: skip


def test_pytest_failures_under_one_directory_trigger_on_running_pytest_there():
    group = [
        incident(("running", "pytest", "tests/e2e/test_a.py")),
        incident(("running", "pytest", "tests/e2e/test_b.py")),
        incident(("running", "pytest", "tests/e2e/sub/test_c.py")),
    ]
    assert trigger_of(group) == Trigger(
        TriggerKind.RUNNING, "pytest", "tests/e2e", "when running pytest on tests/e2e"
    )


def test_a_majority_step_triggers_before_it():
    group = [incident(("before", "git push", ""))] * 3 + [incident(("editing", "", "a/b.py"))]
    assert trigger_of(group) == Trigger(TriggerKind.BEFORE, "git push", "", "before git push")


def test_edits_under_one_directory_trigger_on_editing_there():
    group = [
        incident(("editing", "", "src/db/models.py")),
        incident(("editing", "", "src/db/session.py")),
    ]
    assert trigger_of(group) == Trigger(TriggerKind.EDITING, "", "src/db", "when editing src/db")


def test_nothing_shared_is_no_trigger():
    group = [
        incident(("running", "make", "")),
        incident(("editing", "", "a/b.py")),
        incident(("", "", "")),
    ]
    assert trigger_of(group) is None
    assert trigger_of([]) is None


def test_a_bare_command_with_no_path_has_no_path_in_its_words():
    (only,) = [incident(("running", "make", ""))]
    assert trigger_of([only]).words == "when running make"


def _passing_after(setup, resolution=(), fix=None, reason=NOTHING_CHANGED, key=None, **more):
    records = [command(1, "python app.py"), *setup, command(9, "python app.py", exit_code=0)]
    key = key or ("python", "app.py", "ModuleNotFoundError")
    lesson = failure(key, resolution=resolution, fix=fix, unresolved_because=reason, **more)
    return cards([lesson], records)[0]


def test_an_install_between_failure_and_pass_is_an_environment_fix():
    card = _passing_after(
        [command(2, "pip install requests", exit_code=0)],
        resolution=("re-ran python",), fix_commands=("python app.py",),
        fix=FixKind.CORRECTED_COMMAND, reason=None,
    )  # fmt: skip
    assert card.outcome is Outcome.ENVIRONMENT_FIXED
    assert card.noise is None
    assert card.what_fixed_it == "Fixed the setup: ran `pip install requests`."


def test_npm_install_then_pass_is_an_environment_fix():
    records = [
        command(1, "npm test"), command(2, "npm install", exit_code=0),
        command(3, "npm test", exit_code=0),
    ]  # fmt: skip
    lesson = failure(
        ("npm", "-", "exit 1"), resolution=("ran npm install",),
        unresolved_because=None,
    )  # fmt: skip
    (card,) = cards([lesson], records)
    assert card.outcome is Outcome.ENVIRONMENT_FIXED
    assert card.what_fixed_it == "Fixed the setup: ran `npm install`."


def test_an_unrecognized_setup_command_still_counts_as_the_setup():
    card = _passing_after(
        [command(2, "docker compose up -d", exit_code=0)], key=("python", "app.py", "OSError")
    )
    assert card.outcome is Outcome.ENVIRONMENT_FIXED
    assert card.noise is None
    assert card.what_fixed_it == "Fixed the setup: ran `docker compose up -d`."


def test_a_look_around_between_failure_and_pass_is_not_a_setup():
    card = _passing_after([command(2, "ls", exit_code=0)], key=("python", "app.py", "OSError"))
    assert card.noise is NoiseReason.PLAIN_RETRY


def test_a_broader_rerun_with_nothing_else_is_a_plain_retry():
    records = [command(1, "pytest tests/test_a.py"), command(2, "pytest", exit_code=0)]
    lesson = failure(("pytest", "tests/test_a.py", "exit 1"), unresolved_because=PASSED_RESPELLED)
    (card,) = cards([lesson], records)
    assert card.noise is NoiseReason.PLAIN_RETRY
    assert card.what_fixed_it == "Nothing: it passed when run again."


def test_a_secret_in_the_setup_command_is_scrubbed():
    secret = "abcdefgh" + "12345678"
    card = _passing_after(
        [command(2, f"pip install x --token={secret}", exit_code=0)],
        key=("python", "app.py", "OSError"),
    )
    assert secret not in card.what_fixed_it


def test_the_error_class_is_not_said_twice():
    lesson = failure(("python", "a.py", "ValueError"))
    (card,) = cards([lesson], [command(1, "python a.py", raw="ValueError: bad value")])
    assert (
        card.what_happened
        == "The agent ran python on a.py and it stopped with ValueError: bad value."
    )


def test_repo_names_make_paths_repo_relative():
    lesson = failure(("pytest", "/home/me/shop/tests/test_a.py", "exit 1"))
    (card,) = incidents_from([lesson], {}, {}, frozenset({"shop"}))
    assert card.situation == ("running", "pytest", "tests/test_a.py")


def test_a_failed_install_before_the_pass_did_not_fix_the_setup():
    card = _passing_after(
        [command(2, "pip install x", exit_code=1)], key=("python", "app.py", "OSError")
    )
    assert card.outcome is not Outcome.ENVIRONMENT_FIXED
    assert card.noise is NoiseReason.PLAIN_RETRY


def test_a_setup_step_keeps_its_repo_relative_path():
    from symbiont.miner.incident_words import setup_sentence

    sentence = setup_sentence("rm /home/dev/Code/app/.git/index.lock", frozenset({"app"}))
    assert sentence == "Fixed the setup: ran `rm .git/index.lock`."
