"""The `incidents` data: Inbox groups, cards by topic, noise with reasons, null for no date."""

from dataclasses import replace

import pytest

from quiet_store import mine_a_session_without_failures
from record_builders import edit, run, session, user
from symbiont.miner.incident_types import Incident, NoiseReason, Outcome
from symbiont.miner.painpoint import Signal
from symbiont.miner.screen import ScreenRules
from symbiont.miner.topics import Group, TopicMap
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.service.incident_view import IncidentContext, incident_groups, incidents_snapshot
from symbiont.store.local import Source, Store
from symbiont.store.mining import MiningRules, remine


def card(session, step=1, topic="", noise=None, program="pytest", example="pytest tests"):
    return Incident(
        session_id=session, step=step, signal=Signal.FAILED_COMMAND,
        what_happened=f"The agent ran {program} and it failed.", first_wrong="", cost_steps=0,
        what_fixed_it="Edited app.py, then the command passed.", outcome=Outcome.FIXED_IN_CODE,
        noise=noise, topic=topic, files=("app.py",), situation=("running", program, "tests"),
        fingerprint=f"failure:{program}:boom", example=example,
    )  # fmt: skip


pytestmark = pytest.mark.periphery
IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"
DAYS = {"a": "2026-10-05", "b": "2026-10-06", "c": "2026-10-20", "u": None}


def test_cards_are_grouped_by_topic_newest_first():
    cards = [card("a", topic="Parser"), card("c", topic="Parser"), card("b", topic="Build")]
    context = IncidentContext(topic_descriptions={"Parser": "Fixing the parser"})
    shown = incident_groups(cards, DAYS, context)["topics"]
    assert [t["topic"] for t in shown] == ["Parser", "Build"]
    parser = next(t for t in shown if t["topic"] == "Parser")
    assert [c["date"] for c in parser["worth"]] == ["2026-10-20", "2026-10-05"]
    assert parser["description"] == "Fixing the parser"
    assert parser["sessions"] == 2


def test_all_noise_project_still_lists_the_noise_with_reasons():
    noisy = [
        card("a", topic="Parser", noise=NoiseReason.PLAIN_RETRY),
        card("b", topic="Parser", noise=NoiseReason.PLAIN_RETRY),
        card("c", topic="Parser", noise=NoiseReason.LOOK_AROUND),
    ]
    shown = incident_groups(noisy, DAYS)
    topic = shown["topics"][0]
    assert topic["worth"] == []
    assert topic["noise"] == {"plain_retry": 2, "look_around": 1}
    assert shown["noise"]["total"] == 3
    assert shown["noise"]["byReason"][0]["count"] == 2
    assert shown["groups"][0]["noise"] == "plain_retry"


def test_an_undated_card_says_null():
    shown = incident_groups([card("u")], DAYS)
    group = shown["groups"][0]
    assert shown["noTopic"][0]["date"] is None
    assert (group["first"], group["last"], group["weekly"], group["undated"]) == (None, None, [], 1)


def test_a_group_has_a_real_title_counts_weeks_and_trigger():
    cards = [card("a", example="pytest -x tests/a"), card("b"), card("c")]
    group = incident_groups(cards, DAYS, IncidentContext(titles={"c": "Fix parser"}))["groups"][0]
    assert group["title"] == "pytest tests"
    assert (group["times"], group["sessions"], group["kind"]) == (3, 3, "failure")
    assert group["weekly"] == [["2026-W41", 2], ["2026-W43", 1]]
    assert (group["first"], group["last"]) == ("2026-10-05", "2026-10-20")
    assert group["trigger"]["program"] == "pytest"
    assert group["key"] == "failure:pytest:boom"
    assert group["cards"][0]["session"] == "Fix parser"
    assert group["verdict"] == "fixed in the code"


def test_a_group_without_a_shared_situation_has_no_trigger():
    mixed = [card("a"), card("b", program="npm"), card("c", program="make")]
    shown = incident_groups(mixed, DAYS)
    assert all(g["trigger"] is not None for g in shown["groups"])
    cards = [card("a"), card("b")]
    cards[1] = Incident(**{**cards[1].__dict__, "situation": ("", "", "")})
    assert incident_groups(cards, DAYS)["groups"][0]["trigger"] is None


def test_the_snapshot_of_a_mined_store_reads_topics_and_titles_from_the_review_state(tmp_path):
    store = Store.open(tmp_path / "s.db")
    mine_one_failure(tmp_path, store)
    store.review.summaries.save_topics(
        "demo", TopicMap((Group("Parser work", "Fixing it", ("s1",)),), (), ())
    )
    shown = incidents_snapshot(store, "demo")
    assert shown["topics"][0]["topic"] == "Parser work"
    assert shown["topics"][0]["description"] == "Fixing it"
    assert shown["groups"][0]["key"].startswith("failure:pytest:")


def mine_one_failure(tmp_path, store, reader="jsonl", min_sessions=2):
    steps = session(
        user("fix"),
        run("pytest tests/test_parser.py", 1, IMPORT),
        edit("app/parser.py", diff="-a\n+def parse(text):\n"),
        run("pytest tests/test_parser.py", 0, "1 passed"),
    )
    path = tmp_path / "log.jsonl"
    with path.open("w") as fh:
        dump_jsonl([replace(r, session_id="s1") for r in steps], fh)
    rules = MiningRules(
        {reader: lambda p, project: iter(list(load_jsonl(p.open())))},
        frozenset(),
        screen=ScreenRules(min_sessions=min_sessions),
    )
    remine(store, "demo", rules, adding=[Source("demo", reader, str(path))])


def fixed_card(session, outcome):
    return Incident(**{**card(session).__dict__, "outcome": outcome})


def recurring_of(cards):
    return incident_groups(cards, DAYS)["groups"][0]["recurring"]


def test_a_group_seen_once_and_never_fixed_is_not_recurring():
    assert recurring_of([fixed_card("a", Outcome.NEVER_FIXED)]) is False


def test_a_group_in_two_sessions_is_recurring():
    cards = [fixed_card("a", Outcome.NEVER_FIXED), fixed_card("b", Outcome.NEVER_FIXED)]
    assert recurring_of(cards) is True


def test_a_single_session_group_with_a_code_or_setup_fix_is_recurring():
    assert recurring_of([fixed_card("a", Outcome.FIXED_IN_CODE)]) is True
    assert recurring_of([fixed_card("a", Outcome.ENVIRONMENT_FIXED)]) is True
    assert recurring_of([fixed_card("a", Outcome.PASSED_ON_RETRY)]) is False


def test_a_session_dropped_from_the_topic_map_loses_its_topic(tmp_path):
    store = Store.open(tmp_path / "s.db")
    summaries = store.review.summaries
    summaries.save_topics("demo", TopicMap((Group("Parser work", "x", ("s1",)),), (), ()))
    mine_one_failure(tmp_path, store)
    assert incidents_snapshot(store, "demo")["topics"]
    summaries.save_topics("demo", TopicMap((), (), ()))
    assert incidents_snapshot(store, "demo")["topics"] == []


def test_a_group_has_a_generated_name_and_a_correction_card_carries_its_episode():
    failure = incident_groups([card("a")], DAYS)["groups"][0]
    assert failure["name"] == "pytest failing with boom"
    stepped_in = Incident(
        **{**card("a").__dict__, "signal": Signal.CORRECTION, "fingerprint": "",
           "first_wrong": "Edited the wrong config", "cost_steps": 4}
    )  # fmt: skip
    context = IncidentContext(correction_names={("a", 1): "Config edits"})

    group = incident_groups([stepped_in], DAYS, context)["groups"][0]

    assert group["name"] == "Config edits"
    assert (group["cards"][0]["firstWrong"], group["cards"][0]["costSteps"]) == (
        "Edited the wrong config",
        4,
    )


def test_a_long_generated_name_is_cut_to_what_a_renamed_group_may_hold():
    long = replace(card("a"), fingerprint="failure:pytest:" + "x" * 200)

    name = incident_groups([long], DAYS)["groups"][0]["name"]

    assert len(name) == 80 and name.endswith("\u2026") and name.startswith("pytest failing with xx")


def test_a_fingerprint_that_says_nothing_about_what_broke_falls_back_to_the_command():
    odd = replace(card("a"), fingerprint="anything at all")

    assert incident_groups([odd], DAYS)["groups"][0]["name"] == "pytest failing: tests"


def test_two_groups_of_one_program_with_different_errors_get_different_names():
    cards = [
        replace(card("a"), fingerprint="failure:pytest:ImportError"),
        replace(card("b"), fingerprint="failure:pytest:KeyError"),
    ]
    names = [g["name"] for g in incident_groups(cards, DAYS)["groups"]]
    assert sorted(names) == ["pytest failing with ImportError", "pytest failing with KeyError"]


def test_a_placeholder_message_is_told_in_plain_words_and_stays_distinct_by_path():
    cards = [
        replace(
            card("a"),
            fingerprint="failure:make:exit <n> at <path>",
            situation=("running", "make", "api"),
        ),
        replace(
            card("b"), fingerprint="failure:make:value <n>", situation=("running", "make", "web")
        ),
    ]
    names = [g["name"] for g in incident_groups(cards, DAYS)["groups"]]
    assert len(set(names)) == 2 and all(
        n.startswith("make failing with an unexpected result") for n in names
    )


def test_a_leading_cd_is_dropped_from_the_command_a_group_shows():
    moved = replace(card("a"), example="cd /work/app && pytest tests/test_x.py")
    group = incident_groups([moved], DAYS)["groups"][0]
    assert group["title"] == "pytest tests/test_x.py"


def test_what_fixed_it_comes_from_a_card_with_the_groups_verdict_not_the_newest_card():
    fixed = [replace(card(s), what_fixed_it=f"Fixed it in {s}") for s in ("a", "b")]
    newest_unfixed = replace(
        card("c"), outcome=Outcome.NEVER_FIXED, what_fixed_it="Never fixed in this session."
    )

    group = incident_groups([*fixed, newest_unfixed], DAYS)["groups"][0]

    assert group["verdict"] == "fixed in the code"
    assert group["fixed"] == "Fixed it in b" and group["fixShown"] is True
    assert incident_groups([newest_unfixed], DAYS)["groups"][0]["fixShown"] is False


def test_the_names_the_developer_gave_groups_are_told_with_the_generated_name_they_replace(
    tmp_path,
):
    from datetime import date

    from symbiont.service.developer_names import developer_names

    store = Store.open(tmp_path / "s.db")
    mine_one_failure(tmp_path, store)
    group = incidents_snapshot(store, "demo")["groups"][0]
    store.review.triage.rename("demo", group["key"], "Flaky import", date(2026, 11, 6))
    store.review.triage.rename(
        "demo", "failure:gone:forever", "Left from an older mine", date(2026, 11, 6)
    )

    told = developer_names(store, "demo")

    assert told == [{"was": group["name"], "now": "Flaky import", "of": "failure group"}]


def test_a_store_with_sessions_but_no_incident_rows_sends_null_so_the_page_says_mine_again(
    tmp_path,
):
    store = Store.open(tmp_path / "s.db")
    mine_a_session_without_failures(tmp_path, store)
    assert store.mined.session_facts("demo")
    assert incidents_snapshot(store, "demo") is None


def test_a_project_never_mined_has_an_empty_inbox_not_null(tmp_path):
    shown = incidents_snapshot(Store.open(tmp_path / "s.db"), "demo")
    assert shown is not None and shown["groups"] == []


def test_history_that_is_not_the_developers_own_says_so_for_the_teach_prefill(tmp_path):
    dataset = Store.open(tmp_path / "d.db")
    mine_one_failure(tmp_path, dataset, reader="swe-chat")
    assert incidents_snapshot(dataset, "demo")["ownHistory"] is False
    own = Store.open(tmp_path / "o.db")
    mine_one_failure(tmp_path, own, reader="claude-code")
    assert incidents_snapshot(own, "demo")["ownHistory"] is True


def test_a_correction_groups_key_survives_a_new_topic_map_so_triage_and_names_stay_attached():
    said = Incident(**{**card("a", 4).__dict__, "signal": Signal.CORRECTION, "fingerprint": ""})
    before = IncidentContext(correction_names={("a", 4): "Use pnpm"})
    after = IncidentContext(correction_names={("a", 4): "Package manager"})
    old = incident_groups([said], DAYS, before)["groups"][0]
    new = incident_groups([said], DAYS, after)["groups"][0]
    assert old["key"] == new["key"] == "correction:a:4"
    assert (old["name"], new["name"]) == ("Use pnpm", "Package manager")


def test_a_group_trains_only_when_its_lesson_is_among_the_screens_kept_ones(tmp_path):
    held = Store.open(tmp_path / "h.db")
    mine_one_failure(tmp_path, held, min_sessions=2)
    assert incidents_snapshot(held, "demo")["groups"][0]["trains"] is False
    kept = Store.open(tmp_path / "k.db")
    mine_one_failure(tmp_path, kept, min_sessions=1)
    assert incidents_snapshot(kept, "demo")["groups"][0]["trains"] is True


def test_a_correction_group_never_trains():
    said = Incident(**{**card("a", 4).__dict__, "signal": Signal.CORRECTION, "fingerprint": ""})
    shown = incident_groups(
        [said], DAYS, IncidentContext(trained=frozenset({"failure:pytest:boom"}))
    )
    assert shown["groups"][0]["trains"] is False
