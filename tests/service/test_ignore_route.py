"""POST /lessons/<id>/ignore, POST /ignored/restore and GET /ignored through the service.

Failure guarded against: an ignore that works for a repository nobody allowed, an unknown id
that is accepted quietly, and an Ignored list the page does not show.
"""

import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import replace

import pytest

from record_builders import edit, run, session
from symbiont.miner.lesson_context import Review, Verdict
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.trained import lesson_id
from symbiont.service import server
from symbiont.service.app import ServiceMode
from symbiont.service.wiring import Guards, open_service
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery
PROJECT = "demo"
IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"


def lessons_in(*session_ids):
    steps = []
    for sid in session_ids:
        steps += [
            replace(step, project=PROJECT, session_id=sid)
            for step in session(
                run("pytest tests/test_parser.py", 1, IMPORT),
                edit("app/parser.py", diff="-a\n+def parse(text):\n"),
                run("pytest tests/test_parser.py", 0, "1 passed"),
            )
        ]
    return lessons_from(mine_history(sessions_of(steps), {}), steps)


def rig(tmp_path, *, allow):
    registry = RepoRegistry(tmp_path)
    if allow:
        registry.record_stance(PROJECT, RepoStance.GIVEN)
    lessons = lessons_in("a", "b")
    Store.open(tmp_path / "store.db").save_mining(PROJECT, [], lessons, held_out_tasks=frozenset())
    service = open_service(tmp_path, ServiceMode.RECALL_ONLY, guards=Guards(repos=registry))
    return service, lesson_id(lessons[-1])


def test_ignoring_a_lesson_hides_its_pattern_and_replies_with_the_signature(tmp_path):
    service, ident = rig(tmp_path, allow=True)

    reply = service.respond(f"/lessons/{ident}/ignore", {"project": PROJECT})

    assert reply.status == 200 and reply.body["ignored"] is True
    assert reply.body["signature"]["signal"] == "failed_command"
    assert Store.open(tmp_path / "store.db").lessons(PROJECT) == []


def test_ignoring_an_unknown_lesson_is_a_400_naming_it(tmp_path):
    service, _ = rig(tmp_path, allow=True)

    reply = service.respond("/lessons/nope-1/ignore", {"project": PROJECT})

    assert reply.status == 400 and "nope-1" in str(reply.body)


def test_ignore_needs_an_allowed_project(tmp_path):
    service, ident = rig(tmp_path, allow=False)

    reply = service.respond(f"/lessons/{ident}/ignore", {"project": PROJECT})

    assert reply.status == 400 and "repo allow" in str(reply.body)
    assert len(Store.open(tmp_path / "store.db").lessons(PROJECT)) == 2


def test_restore_brings_the_lessons_back_and_a_second_restore_is_a_400(tmp_path):
    service, ident = rig(tmp_path, allow=True)
    signature = service.respond(f"/lessons/{ident}/ignore", {"project": PROJECT}).body["signature"]

    first = service.respond("/ignored/restore", {"project": PROJECT, **signature})
    second = service.respond("/ignored/restore", {"project": PROJECT, **signature})

    assert first.status == 200
    assert len(Store.open(tmp_path / "store.db").lessons(PROJECT)) == 2
    assert second.status == 400 and "not ignored" in str(second.body)


def test_the_page_lists_ignored_patterns_with_their_labels(tmp_path):
    service, ident = rig(tmp_path, allow=True)
    service.respond(f"/lessons/{ident}/ignore", {"project": PROJECT})
    httpd = server.bind(service, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        html = urllib.request.urlopen(f"{base}/dashboard?project={PROJECT}").read().decode()
        listed = json.loads(urllib.request.urlopen(f"{base}/ignored?project={PROJECT}").read())
        script = urllib.request.urlopen(f"{base}/dashboard/ignored.js")
    finally:
        httpd.shutdown()
        httpd.server_close()

    data = json.loads(re.search(r'id="symbiont-data">(.*?)</script>', html, re.S).group(1))
    assert data["painPoints"] == []
    (entry,) = data["ignored"]
    assert entry["label"] and entry == listed["ignored"][0]
    assert script.status == 200


def other_trouble(session_id):
    (found,) = [
        replace(
            item,
            pain_point=replace(
                item.pain_point,
                signature=replace(
                    item.pain_point.signature, key=("pytest", "tests/test_other.py", "KeyError")
                ),
            ),
        )
        for item in lessons_in(session_id)
    ]
    return found


def merged_rig(tmp_path):
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    first, second = lessons_in("a", "b")[-1], other_trouble("c")
    store = Store.open(tmp_path / "store.db")
    store.save_mining(PROJECT, [], [first, second], held_out_tasks=frozenset())
    store.curation.save_review(
        PROJECT,
        lesson_id(second),
        Review(Verdict.MISTAKE, title="One merged row", merge_with=lesson_id(first)),
    )
    service = open_service(tmp_path, ServiceMode.RECALL_ONLY, guards=Guards(repos=registry))
    return service, lesson_id(first), lesson_id(second)


def test_ignoring_a_merged_row_hides_all_its_lessons_after_a_reload_and_restore_returns_them(
    tmp_path,
):
    service, first, _ = merged_rig(tmp_path)

    reply = service.respond(f"/lessons/{first}/ignore", {"project": PROJECT})

    assert reply.status == 200 and len(reply.body["signatures"]) == 2
    reopened = Store.open(tmp_path / "store.db")
    assert reopened.lessons(PROJECT) == []
    assert [label for _, label in reopened.ignored.listed(PROJECT)] == [reply.body["label"]]
    one = reply.body["signatures"][1]
    assert service.respond("/ignored/restore", {"project": PROJECT, **one}).status == 200
    assert len(Store.open(tmp_path / "store.db").lessons(PROJECT)) == 2


def test_the_ignored_label_is_the_title_the_dashboard_shows_for_that_row(tmp_path):
    service, first, _ = merged_rig(tmp_path)

    reply = service.respond(f"/lessons/{first}/ignore", {"project": PROJECT})

    assert reply.body["label"] == "One merged row"


def test_listing_ignored_patterns_needs_an_allowed_project(tmp_path):
    service, _ = rig(tmp_path, allow=False)
    httpd = server.bind(service, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/ignored?project={PROJECT}"
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(url)
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert refused.value.code == 400 and "repo allow" in refused.value.read().decode()
