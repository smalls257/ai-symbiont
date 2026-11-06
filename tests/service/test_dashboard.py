"""The dashboard page is built from the repository's store and served by the local service.

Failures guarded against: a page that shows invented data (the product dashboard carries no fixed
research results), and a demo label on real data.
"""

import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import date

import pytest

from record_builders import edit, run, session
from symbiont.miner.lesson_context import (
    AppliesTo,
    AuthoredLesson,
    LessonContext,
    LessonKind,
    Review,
    Verdict,
)
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.trained import lesson_id
from symbiont.miner.twins import merge_twins
from symbiont.service import server
from symbiont.service.app import ServiceMode
from symbiont.service.dashboard_page import Live, dashboard_page
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
from symbiont.service.mining_jobs import MiningProgress, MiningState
from symbiont.service.nightly import NightlyJudges, NightlyRecord, lessons_digest, write_record
from symbiont.service.wiring import Guards, open_service
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery
IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"
TODAY = date(2026, 11, 2)


def lessons_in(*session_ids):
    steps = []
    for sid in session_ids:
        steps += [
            replace(step, project="demo", session_id=sid)
            for step in session(
                run("pytest tests/test_parser.py", 1, IMPORT),
                edit("app/parser.py", diff="-a\n+def parse(text):\n"),
                run("pytest tests/test_parser.py", 0, "1 passed"),
            )
        ]
    return lessons_from(mine_history(sessions_of(steps), {}), steps)


def view(lessons, **extra):
    dates = {"a": date(2026, 10, 3), "b": date(2026, 10, 20), "c": date(2026, 10, 31)}
    return RepoView("demo", lessons, {}, dates, **extra)


def test_repeats_of_one_trouble_become_one_pain_point_with_its_sessions_and_replay():
    data = dashboard_snapshot(view(lessons_in("a", "b", "c")), TODAY)

    (point,) = data["painPoints"]
    assert data["schema"] == 1 and data["repo"]["demo"] is False
    assert point["kind"] == "repeat" and point["sessions"] == [0, 1, 2]
    assert [s["date"] for s in data["sessions"]] == ["2026-10-03", "2026-10-20", "2026-10-31"]
    assert [item["sessionIndex"] for item in data["replay"]["items"]] == [1, 2]
    assert "proof" not in data


def test_a_verdict_title_and_tags_reach_the_page_and_the_users_words_lead():
    lessons = lessons_in("a", "b")
    ident = lesson_id(lessons[-1])
    reviews = {
        ident: Review(
            Verdict.MISTAKE, "Keep imports lazy.", "Lazy imports", None, AppliesTo(("parser",), ())
        )
    }
    contexts = {ident: LessonContext("Startup time matters.")}

    data = dashboard_snapshot(RepoView("demo", lessons, contexts, {}, reviews), TODAY)

    (point,) = data["painPoints"]
    (lesson,) = data["lessons"]
    assert point["title"] == "Lazy imports"
    assert lesson["context"] == "Startup time matters." and lesson["verdict"] == "mistake"
    assert lesson["appliesTo"]["terms"] == ["parser"]


def test_written_lessons_appear_as_pain_points_even_in_a_repository_with_no_mined_sessions():
    written = [AuthoredLesson("w1", "Refunds never retry.", LessonKind.RULE, ("src/refund.py",))]

    data = dashboard_snapshot(RepoView("demo", [], {}, {}, written=written), TODAY)

    (point,) = data["painPoints"]
    assert point["kind"] == "rule" and point["file"] == "src/refund.py" and data["sessions"]


def test_a_reviewer_can_merge_one_pain_point_into_another():
    first = lessons_in("a")
    other = [
        replace(
            lesson,
            pain_point=replace(
                lesson.pain_point,
                signature=replace(
                    lesson.pain_point.signature, key=("pytest", "tests/test_other.py", "KeyError")
                ),
            ),
        )
        for lesson in lessons_in("b")
    ]
    merge = {lesson_id(other[0]): Review(Verdict.MISTAKE, merge_with=lesson_id(first[0]))}

    data = dashboard_snapshot(view([*first, *other], reviews=merge), TODAY)

    assert len(data["painPoints"]) == 1 and data["painPoints"][0]["sessions"] == [0, 1]


@pytest.fixture
def served(tmp_path):
    store = Store.open(tmp_path / "store.db")
    store.save_mining("demo", [], lessons_in("a", "b"), held_out_tasks=frozenset())
    httpd = server.bind(open_service(tmp_path, ServiceMode.RECALL_ONLY), 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", store
    httpd.shutdown()
    httpd.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url) as reply:
            return reply.status, reply.read().decode(), reply.headers["Content-Type"]
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(), error.headers["Content-Type"]


def test_the_service_serves_the_page_filled_from_the_store_and_its_static_files(served):
    base, _ = served

    status, html, kind = get(f"{base}/dashboard")
    data = json.loads(re.search(r'id="symbiont-data">(.*?)</script>', html, re.S).group(1))

    assert status == 200 and kind.startswith("text/html")
    assert data["repo"]["name"] == "demo" and len(data["painPoints"]) == 1
    assert "501" not in html and "measured results" not in html
    assert "Every note it showed" not in html and "mockup" not in html.lower()
    assert get(f"{base}/dashboard/dashboard.js")[2].startswith("text/javascript")
    assert get(f"{base}/dashboard/painlist.js")[2].startswith("text/javascript")
    assert get(f"{base}/dashboard/dashboard.css")[0] == 200
    assert "http://" not in get(f"{base}/dashboard/dashboard.js")[1].replace("http://127", "")


def test_several_repositories_need_a_choice_and_an_unknown_path_is_a_404(served):
    base, store = served
    store.save_mining("other", [], lessons_in("c"), held_out_tasks=frozenset())

    status, body, _ = get(f"{base}/dashboard")

    assert status == 400 and "demo, other" in body
    assert get(f"{base}/dashboard?project=other")[0] == 200
    assert get(f"{base}/nope")[0] == 404


def test_the_demo_label_exists_only_behind_the_demo_query(served):
    base, _ = served
    js = get(f"{base}/dashboard/dashboard.js")[1]

    assert 'get("demo")==="1"' in js and 'DEMO?""' in js


def test_the_snapshot_carries_the_nightly_state_for_the_header():
    state = {"state": "stale", "sentence": "stale: x", "lessons": 3, "trained_at": None}
    assert dashboard_snapshot(view(lessons_in("a"), nightly=state), TODAY)["nightly"] == state
    assert dashboard_snapshot(view(lessons_in("a")), TODAY)["nightly"] is None


def test_the_served_page_says_never_trained_then_trained_after_a_night(tmp_path):
    store = Store.open(tmp_path / "store.db")
    lessons = lessons_in("a", "b")
    store.save_mining("demo", [], lessons, held_out_tasks=frozenset())
    nightly = NightlyJudges(tmp_path / "nightly")
    service = open_service(tmp_path, ServiceMode.RECALL_ONLY, guards=Guards(nightly_news=nightly))

    def page_data():
        html = service.page("/dashboard?project=demo").body.decode()
        return json.loads(re.search(r'id="symbiont-data">(.*?)</script>', html, re.S).group(1))

    assert page_data()["nightly"]["state"] == "never"
    record = NightlyRecord(
        lessons_digest(merge_twins(lessons)), "http://127.0.0.1:1", 2, "t", "mlx"
    )
    write_record(tmp_path / "nightly", "demo", record)
    assert page_data()["nightly"]["state"] == "trained"
    assert 'id="nightly"' in service.page("/dashboard?project=demo").body.decode()
    assert "DATA.nightly" in service.page("/dashboard/dashboard.js").body.decode()


def _mining_shell(page):
    data = re.search(r'id="symbiont-data">(.*?)</script>', page.body.decode(), re.S).group(1)
    return json.loads(data).get("mining")


def test_the_mine_address_keeps_the_mine_stage_up_for_a_job_that_already_finished(served):
    _, store = served
    done = MiningProgress(MiningState.DONE, 6, 6, 14, 5, 9)
    live = Live(mining=lambda project: done)

    watching = dashboard_page(store, None, "/dashboard?project=demo&mining=1", TODAY, live)
    plain = dashboard_page(store, None, "/dashboard?project=demo", TODAY, live)

    assert _mining_shell(watching)["progress"]["lessons"] == 9
    assert _mining_shell(plain) is None


def test_the_mine_address_without_any_job_shows_the_dashboard_not_an_empty_stage(served):
    _, store = served

    page = dashboard_page(store, None, "/dashboard?project=demo&mining=1", TODAY, Live())

    assert _mining_shell(page) is None


def test_the_snapshot_shows_struggle_churn_and_held_back_counts_but_no_lessons_for_them():
    from datetime import date

    from symbiont.miner.churn import FileChurn
    from symbiont.miner.painpoint import Signal, Signature
    from symbiont.miner.screen import HoldReason
    from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
    from symbiont.store.held_back import StruggleGroup

    trap = Signature(Signal.FAILED_COMMAND, ("make", "lint", "exit 2"))
    view = RepoView(
        "demo",
        [],
        {},
        {},
        held_back={HoldReason.NO_FIX_SHOWN: 3},
        struggle=[StruggleGroup(trap, sessions=4, occurrences=10)],
        churn=[FileChurn("a.py", "s1", 3), FileChurn("a.py", "s2", 2), FileChurn("b.py", "s1", 1)],
    )
    shown = dashboard_snapshot(view, date(2026, 11, 6))
    assert shown["heldBack"] == {"no_fix_shown": 3}
    assert shown["painPoints"] == [] and shown["lessons"] == []
    assert (shown["struggle"][0]["sessions"], shown["struggle"][0]["occurrences"]) == (4, 10)
    assert shown["struggle"][0]["minutes"] == 7.0
    assert shown["churn"] == [
        {"file": "a.py", "edits": 5, "sessions": 2},
        {"file": "b.py", "edits": 1, "sessions": 1},
    ]


def _css_rule(css: str, selector: str) -> str:
    match = re.search(r"(?m)^" + re.escape(selector) + r"\{([^}]*)\}", css)
    assert match, f"no {selector} rule in dashboard.css"
    return match.group(1)


def test_the_add_context_panels_scroll_instead_of_clipping():
    """Paper Tiger: a panel that shows a candidate but clips most of a long quote."""
    from pathlib import Path

    css = (Path(server.__file__).parent / "static" / "dashboard.css").read_text()
    edit_rule = _css_rule(css, ".edit")
    agent_rule = _css_rule(css, ".agent")
    for rule in (edit_rule, agent_rule):
        assert "overflow-y:auto" in rule
        assert "min-height:0" in rule
    assert "overflow:hidden" not in edit_rule
