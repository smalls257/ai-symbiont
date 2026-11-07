"""POST /triage through the service, and the `triage` key on the dashboard snapshot.

Failure guarded against: a status saved for a repository nobody allowed, an unknown state or an
Archived group with no way back accepted quietly, a change with no event, and a saved status
the page never shows.
"""

import json
import re
from datetime import date, timedelta

import pytest

from symbiont.core.triage import GroupActivity, GroupState, ReturnRule, triage_row
from symbiont.service.app import ServiceMode
from symbiont.service.triage_route import group_activity, triage_listing
from symbiont.service.wiring import Guards, open_service
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery
PROJECT = "demo"
KEY = "group-made-up-1"
TODAY = date(2026, 11, 7)
DAY = date(2026, 10, 10)
WHEN = (TODAY, [])


def rig(tmp_path, *, allow=True):
    registry = RepoRegistry(tmp_path)
    if allow:
        registry.record_stance(PROJECT, RepoStance.GIVEN)
    return open_service(tmp_path, ServiceMode.RECALL_ONLY, guards=Guards(repos=registry))


def body(**fields):
    return {"project": PROJECT, "group_key": KEY, **fields}


def saved(tmp_path):
    return Store.open(tmp_path / "store.db").review.triage.all(PROJECT)


def test_resolving_a_group_saves_it_dated_today(tmp_path):
    reply = rig(tmp_path).respond("/triage", body(state="resolved"))

    assert reply.status == 200 and reply.body["state"] == "resolved"
    assert saved(tmp_path)[KEY].changed_on == date.today()


def test_archiving_after_sessions_saves_the_rule_and_count(tmp_path):
    rig(tmp_path).respond(
        "/triage", body(state="archived", return_rule="after_sessions", after_sessions=4)
    )

    assert saved(tmp_path)[KEY] == triage_row(
        GroupState.ARCHIVED, ReturnRule.AFTER_SESSIONS, 4, date.today()
    )


@pytest.mark.parametrize(
    ("fields", "named"),
    [
        ({"state": "bogus"}, "bogus"),
        ({"state": ["resolved"]}, "state"),
        ({"state": "archived", "return_rule": ["never"]}, "return_rule"),
        ({"state": "archived"}, "return_rule"),
        ({"state": "archived", "return_rule": "after_sessions"}, "after_sessions"),
        (
            {"state": "archived", "return_rule": "after_sessions", "after_sessions": 0},
            "after_sessions",
        ),
        (
            {"state": "archived", "return_rule": "after_sessions", "after_sessions": "3"},
            "after_sessions",
        ),
        ({"state": "archived", "return_rule": "sometimes"}, "sometimes"),
        ({"state": "resolved", "return_rule": "never"}, "return rule"),
        ({}, "taught"),
        ({"taught": False}, "taught"),
        ({"state": "reviewed", "extra": 1}, "extra"),
    ],
)
def test_a_bad_request_is_a_400_naming_the_problem_and_saves_nothing(tmp_path, fields, named):
    reply = rig(tmp_path).respond("/triage", body(**fields))

    assert reply.status == 400 and named in str(reply.body)
    assert saved(tmp_path) == {}


def test_an_empty_group_key_and_a_missing_project_are_400s(tmp_path):
    service = rig(tmp_path)

    assert service.respond("/triage", body(state="reviewed", group_key="")).status == 400
    assert service.respond("/triage", {"group_key": KEY, "state": "reviewed"}).status == 400


def test_triage_needs_an_allowed_project(tmp_path):
    reply = rig(tmp_path, allow=False).respond("/triage", body(state="resolved"))

    assert reply.status == 400 and "repo allow" in str(reply.body)
    assert saved(tmp_path) == {}


def test_taught_records_the_day_without_changing_the_state(tmp_path):
    service = rig(tmp_path)
    service.respond("/triage", body(state="reviewed"))

    reply = service.respond("/triage", body(taught=True))

    assert reply.status == 200 and reply.body["taught_on"] == date.today().isoformat()
    assert saved(tmp_path)[KEY].state is GroupState.REVIEWED


def add_lesson(service, text):
    reply = service.respond(
        "/lessons/add",
        {"project": PROJECT, "lessons": [{"text_in_plain_words": text, "kind": "mistake"}]},
    )
    assert reply.status == 200
    return reply.body["ids"][0]


def test_taught_keeps_the_id_of_the_lesson_it_stored_and_a_later_teach_without_one_keeps_it(
    tmp_path,
):
    service = rig(tmp_path)
    ident = add_lesson(service, "Unset the token first.")

    service.respond("/triage", body(taught=True, lesson_id=ident))
    service.respond("/triage", body(taught=True))

    ids = Store.open(tmp_path / "store.db").review.triage.lesson_ids(PROJECT)
    assert ids == {KEY: ident}


def test_a_lesson_id_nobody_stored_is_a_400_naming_it(tmp_path):
    reply = rig(tmp_path).respond("/triage", body(taught=True, lesson_id="nope"))

    assert reply.status == 400 and "nope" in str(reply.body)


def test_a_lesson_id_that_is_not_text_is_a_400(tmp_path):
    reply = rig(tmp_path).respond("/triage", body(taught=True, lesson_id=5))

    assert reply.status == 400 and "lesson_id" in str(reply.body)


def test_every_triage_call_writes_an_event_and_a_refusal_too(tmp_path):
    service = rig(tmp_path)
    service.respond("/triage", body(state="resolved"))
    service.respond("/triage", body(state="bogus"))

    log = next((tmp_path / "runs").glob("*/events.jsonl"))
    events = [json.loads(line) for line in log.read_text().splitlines()]

    assert [e["route"] for e in events] == ["triage", "triage"]
    assert events[0]["triage"] == {
        "group_key": KEY,
        "state": "resolved",
        "taught_on": None,
        "name": "",
    }
    assert events[1]["status"] == 400


def test_the_page_carries_the_triage_of_each_group(tmp_path):
    service = rig(tmp_path)
    service.respond("/triage", body(state="resolved"))

    page = service.page(f"/dashboard?project={PROJECT}")

    data = json.loads(re.search(r'id="symbiont-data">(.*?)</script>', page.body.decode(), re.S)[1])
    assert data["triage"] == {
        KEY: {
            "state": "resolved",
            "regressed": False,
            "taught_on": None,
            "name": "",
            "changed_on": date.today().isoformat(),
            "return_rule": None,
        }
    }


def test_a_resolved_group_seen_again_is_listed_for_review_and_regressed(tmp_path):
    store = Store.open(tmp_path / "store.db")
    store.review.triage.save(
        PROJECT, KEY, triage_row(GroupState.RESOLVED, None, None, date.today())
    )

    listing = triage_listing(
        store, PROJECT, date.today(), {KEY: GroupActivity(1, seen_in_new_session=True)}
    )

    assert listing[KEY] == {
        "state": "for_review",
        "regressed": True,
        "taught_on": None,
        "name": "",
        "changed_on": date.today().isoformat(),
        "return_rule": None,
    }


def test_a_name_is_trimmed_saved_and_shown_and_an_empty_name_restores_the_generated_one(tmp_path):
    service = rig(tmp_path)

    reply = service.respond("/triage", body(name="  Flaky login  "))

    assert reply.status == 200 and reply.body["name"] == "Flaky login"
    assert reply.body["state"] == "for_review"
    page = service.page(f"/dashboard?project={PROJECT}")
    data = json.loads(re.search(r'id="symbiont-data">(.*?)</script>', page.body.decode(), re.S)[1])
    assert data["triage"][KEY]["name"] == "Flaky login"
    assert service.respond("/triage", body(name="   ")).body["name"] == ""


def test_a_name_may_travel_with_a_state_and_the_state_is_kept_when_only_renaming(tmp_path):
    service = rig(tmp_path)
    service.respond("/triage", body(state="resolved", name="Docker build"))

    service.respond("/triage", body(name="Docker build, again"))

    assert saved(tmp_path)[KEY].state is GroupState.RESOLVED


@pytest.mark.parametrize("name", ["x" * 81, 7, None, ["a"]])
def test_a_name_over_80_characters_or_not_text_is_a_400_and_saves_nothing(tmp_path, name):
    reply = rig(tmp_path).respond("/triage", body(name=name))

    assert reply.status == 400 and "name" in str(reply.body)
    assert saved(tmp_path) == {}


def test_a_name_of_exactly_80_characters_is_kept(tmp_path):
    assert rig(tmp_path).respond("/triage", body(name="x" * 80)).status == 200


def test_a_bad_state_sent_with_a_name_saves_neither(tmp_path):
    reply = rig(tmp_path).respond("/triage", body(state="bogus", name="Docker build"))

    assert reply.status == 400
    assert saved(tmp_path) == {}


def groups_seen_on(*days):
    cards = [{"sessionId": f"s{n}", "date": day} for n, day in enumerate(days)]
    return [{"key": KEY, "cards": cards}]


def test_a_resolved_group_seen_in_a_later_session_is_regressed_on_the_page_data(tmp_path):
    store = Store.open(tmp_path / "store.db")
    store.review.triage.save(
        PROJECT, KEY, triage_row(GroupState.RESOLVED, None, None, date(2026, 10, 10))
    )

    seen = group_activity(store, PROJECT, groups_seen_on("2026-10-05", "2026-10-20", None), WHEN)
    listing = triage_listing(store, PROJECT, TODAY, seen)

    assert listing[KEY]["state"] == "for_review" and listing[KEY]["regressed"] is True


def test_a_resolved_group_not_seen_since_stays_resolved_and_an_untriaged_one_has_no_entry(tmp_path):
    store = Store.open(tmp_path / "store.db")
    store.review.triage.save(
        PROJECT, KEY, triage_row(GroupState.RESOLVED, None, None, date(2026, 10, 10))
    )

    quiet = group_activity(store, PROJECT, groups_seen_on("2026-10-05", None), WHEN)

    assert triage_listing(store, PROJECT, TODAY, quiet)[KEY] == {
        "state": "resolved",
        "regressed": False,
        "taught_on": None,
        "name": "",
        "changed_on": "2026-10-10",
        "return_rule": None,
    }
    assert group_activity(store, PROJECT, [{"key": "other", "cards": []}], WHEN) == {}


def test_renaming_a_regressed_group_keeps_it_regressed(tmp_path):
    store = Store.open(tmp_path / "store.db")
    store.review.triage.save(
        PROJECT, KEY, triage_row(GroupState.RESOLVED, None, None, date(2026, 10, 10))
    )
    seen = group_activity(store, PROJECT, groups_seen_on("2026-10-05", "2026-10-20"), WHEN)
    assert triage_listing(store, PROJECT, TODAY, seen)[KEY]["regressed"] is True

    store.review.triage.rename(PROJECT, KEY, "Docker build", date(2026, 10, 25))

    seen = group_activity(store, PROJECT, groups_seen_on("2026-10-05", "2026-10-20"), WHEN)
    listing = triage_listing(store, PROJECT, TODAY, seen)[KEY]
    assert listing["regressed"] is True and listing["name"] == "Docker build"
    assert listing["state"] == "for_review"


def test_the_listing_tells_when_the_state_was_set_and_when_an_archived_group_returns(tmp_path):
    store = Store.open(tmp_path / "store.db")
    row = triage_row(GroupState.ARCHIVED, ReturnRule.AFTER_SESSIONS, 5, date(2026, 10, 10))
    store.review.triage.save(PROJECT, KEY, row)
    store.review.triage.save(
        PROJECT, "other", triage_row(GroupState.ARCHIVED, ReturnRule.NEVER, None, date(2026, 9, 1))
    )

    listing = triage_listing(store, PROJECT, TODAY)

    assert listing[KEY]["changed_on"] == "2026-10-10"
    assert listing[KEY]["return_rule"] == "after_sessions"
    assert listing[KEY]["after_sessions"] == 5
    assert listing["other"]["return_rule"] == "never"
    assert "after_sessions" not in listing["other"]


def test_archiving_until_worse_saves_the_rule_and_no_count_or_day(tmp_path):
    reply = rig(tmp_path).respond("/triage", body(state="archived", return_rule="until_worse"))

    assert reply.status == 200
    assert saved(tmp_path)[KEY] == triage_row(
        GroupState.ARCHIVED, ReturnRule.UNTIL_WORSE, None, date.today()
    )


def test_archiving_for_30_days_saves_the_day_thirty_days_from_the_service_clock(tmp_path):
    reply = rig(tmp_path).respond("/triage", body(state="archived", return_rule="on_date"))

    assert reply.status == 200
    assert saved(tmp_path)[KEY].until == date.today() + timedelta(days=30)


@pytest.mark.parametrize(
    "fields",
    [
        {"state": "archived", "return_rule": "until_worse", "after_sessions": 2},
        {"state": "archived", "return_rule": "on_date", "after_sessions": 2},
        {"state": "archived", "return_rule": "on_date", "until": "2026-12-06"},
        {"state": "resolved", "return_rule": "on_date"},
    ],
)
def test_the_new_rules_refuse_a_body_that_does_not_fit_and_save_nothing(tmp_path, fields):
    reply = rig(tmp_path).respond("/triage", body(**fields))

    assert reply.status == 400
    assert saved(tmp_path) == {}


def test_an_on_date_group_comes_back_on_its_day_and_not_before(tmp_path):
    store = Store.open(tmp_path / "store.db")
    store.review.triage.save(
        PROJECT,
        KEY,
        triage_row(GroupState.ARCHIVED, ReturnRule.ON_DATE, None, DAY, date(2026, 12, 6)),
    )

    before = triage_listing(store, PROJECT, date(2026, 12, 5))[KEY]
    on_day = triage_listing(store, PROJECT, date(2026, 12, 6))[KEY]

    assert (before["state"], before["regressed"]) == ("archived", False)
    assert (on_day["state"], on_day["regressed"]) == ("for_review", True)


def test_an_until_worse_group_comes_back_when_its_recent_rate_jumps(tmp_path):
    store = Store.open(tmp_path / "store.db")
    store.review.triage.save(
        PROJECT,
        KEY,
        triage_row(GroupState.ARCHIVED, ReturnRule.UNTIL_WORSE, None, date(2026, 10, 1)),
    )
    cards = [{"sessionId": f"s{n}", "date": f"2026-11-{n + 1:02d}"} for n in range(6)]
    groups = [{"key": KEY, "cards": cards}]
    session_days = [date(2026, 11, n + 1) for n in range(12)] + [date(2026, 9, 20)]

    seen = group_activity(store, PROJECT, groups, (date(2026, 11, 12), session_days))

    listing = triage_listing(store, PROJECT, date(2026, 11, 12), seen)[KEY]
    assert (listing["state"], listing["regressed"]) == ("for_review", True)


def test_the_listing_carries_the_until_day_only_when_the_row_has_one(tmp_path):
    store = Store.open(tmp_path / "store.db")
    row = triage_row(GroupState.ARCHIVED, ReturnRule.ON_DATE, None, DAY, date(2026, 12, 6))
    store.review.triage.save(PROJECT, KEY, row)
    store.review.triage.save(PROJECT, "n", triage_row(GroupState.RESOLVED, None, None, DAY))

    listing = triage_listing(store, PROJECT, date(2026, 12, 1))

    assert listing[KEY]["until"] == "2026-12-06" and "until" not in listing["n"]
