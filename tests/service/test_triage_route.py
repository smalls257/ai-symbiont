"""POST /triage through the service, and the `triage` key on the dashboard snapshot.

Failure guarded against: a status saved for a repository nobody allowed, an unknown state or an
Archived group with no way back accepted quietly, a change with no event, and a saved status
the page never shows.
"""

import json
import re
from datetime import date

import pytest

from symbiont.core.triage import GroupActivity, GroupState, ReturnRule, triage_row
from symbiont.service.app import ServiceMode
from symbiont.service.triage_route import triage_listing
from symbiont.service.wiring import Guards, open_service
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery
PROJECT = "demo"
KEY = "group-made-up-1"


def rig(tmp_path, *, allow=True):
    registry = RepoRegistry(tmp_path)
    if allow:
        registry.record_stance(PROJECT, RepoStance.GIVEN)
    return open_service(tmp_path, ServiceMode.RECALL_ONLY, guards=Guards(repos=registry))


def body(**fields):
    return {"project": PROJECT, "group_key": KEY, **fields}


def saved(tmp_path):
    return Store.open(tmp_path / "store.db").triage.all(PROJECT)


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
    }
    assert events[1]["status"] == 400


def test_the_page_carries_the_triage_of_each_group(tmp_path):
    service = rig(tmp_path)
    service.respond("/triage", body(state="resolved"))

    page = service.page(f"/dashboard?project={PROJECT}")

    data = json.loads(re.search(r'id="symbiont-data">(.*?)</script>', page.body.decode(), re.S)[1])
    assert data["triage"] == {KEY: {"state": "resolved", "regressed": False, "taught_on": None}}


def test_a_resolved_group_seen_again_is_listed_for_review_and_regressed(tmp_path):
    store = Store.open(tmp_path / "store.db")
    store.triage.save(PROJECT, KEY, triage_row(GroupState.RESOLVED, None, None, date.today()))

    listing = triage_listing(store, PROJECT, {KEY: GroupActivity(1, seen_in_new_session=True)})

    assert listing[KEY] == {"state": "for_review", "regressed": True, "taught_on": None}
