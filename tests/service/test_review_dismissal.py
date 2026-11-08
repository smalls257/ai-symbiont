"""Dismissing a review group through POST /triage: it stays dismissed on the page after a re-mine.

Failure guarded against: Silent Fallback (a dismissed group returning because the re-mine
renamed it) and Black Box (a page that does not carry the reviews at all).
"""

import json
import re

import pytest

from review_builders import NULLS, OTHER, flag
from store_builders import save_lessons
from symbiont.service.app import ServiceMode
from symbiont.service.wiring import Guards, open_service
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery
PROJECT = "demo"


def rig(tmp_path):
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    return open_service(tmp_path, ServiceMode.RECALL_ONLY, guards=Guards(repos=registry))


def store_lessons(tmp_path, lessons):
    save_lessons(
        Store.open(tmp_path / "store.db"), PROJECT, [], lessons, held_out_tasks=frozenset()
    )


def reviews_on_page(service):
    page = service.page(f"/dashboard?project={PROJECT}").body.decode()
    return json.loads(re.search(r'id="symbiont-data">(.*?)</script>', page, re.S)[1])["reviews"]


def test_the_page_carries_the_review_groups(tmp_path):
    store_lessons(tmp_path, [OTHER, *NULLS])
    shown = reviews_on_page(rig(tmp_path))
    assert [g["count"] for g in shown["groups"]] == [2, 1]


def test_a_dismissed_group_stays_dismissed_after_a_re_mine_adds_an_older_member(tmp_path):
    store_lessons(tmp_path, NULLS)
    service = rig(tmp_path)
    (group,) = reviews_on_page(service)["groups"]
    reply = service.respond(
        "/triage",
        {
            "project": PROJECT,
            "group_key": group["key"],
            "state": "archived",
            "return_rule": "never",
        },
    )
    assert reply.status == 200
    older = flag("s0", 1, "Another null dereference on an empty batch", path="src/a.ts")
    store_lessons(tmp_path, [older, *NULLS])
    shown = reviews_on_page(service)
    assert shown["groups"] == [] and shown["dismissed"] == 1


def test_dismissing_one_group_leaves_another_from_the_same_fetch_shown(tmp_path):
    nulls = flag("s1", 5, "Possible null dereference when the batch is empty")
    rename = flag("s1", 5, "Rename the retry timeout constant", path="src/retry.ts")
    store_lessons(tmp_path, [nulls, rename])
    service = rig(tmp_path)
    groups = reviews_on_page(service)["groups"]
    target = next(g for g in groups if "null" in g["gist"])
    body = {"project": PROJECT, "group_key": target["key"], "state": "archived"}
    reply = service.respond("/triage", body | {"return_rule": "never"})
    assert reply.status == 200
    shown = reviews_on_page(service)
    assert [g["gist"] for g in shown["groups"]] == ["Rename the retry timeout constant"]
    assert shown["dismissed"] == 1
