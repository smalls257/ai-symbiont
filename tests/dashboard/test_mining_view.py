"""What the Mine stage says for each state of a mining job.

Failures guarded against: a Silent Fallback (a failed or empty run that renders as a blank
dashboard, or that reloads into a view of nothing) and a Paper Tiger (a progress bar that moves but
whose numbers are not the service's). The pure `describe` function runs under node with no DOM;
node is a hard requirement here as it is for the JavaScript gate (QG-FE-01), never a skip.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
MINING_JS = HERE.parents[1] / "src" / "symbiont" / "service" / "static" / "mining.js"


@pytest.fixture(scope="module")
def views():
    node = shutil.which("node")
    assert node, "node is required for the dashboard tests (the JS gate needs it too)"
    out = subprocess.run(  # noqa: S603
        [node, str(HERE / "mining_view_harness.js"), str(MINING_JS)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_a_running_job_shows_the_services_counts_and_keeps_polling(views):
    running = views["running"]

    assert running["next"] == "poll" and running["failed"] is False
    assert running["counts"] == [12, 3, 2, 4] and running["percent"] == 30
    assert running["headline"] == "Reading 40 sessions"
    assert running["status"] == "session 12 of 40 · 3 pain points so far"
    assert running["feed"] == ["`pytest x` failed with ImportError"]


def test_a_done_job_with_lessons_opens_the_pain_point_view(views):
    done = views["done"]

    assert done["next"] == "reload" and done["percent"] == 100
    assert done["headline"] == "Found 5 pain points in 40 sessions."
    assert done["status"] == "done · 9 lessons ready to use"


def test_a_done_job_with_no_lessons_says_so_and_does_not_reload_into_nothing(views):
    empty = views["doneEmpty"]

    assert empty["next"] == "stop" and empty["failed"] is False
    assert "found no pain points" in empty["headline"]


def test_a_failed_job_shows_its_reason_and_stops(views):
    failed = views["failed"]

    assert failed["failed"] is True and failed["next"] == "stop"
    assert failed["lede"] == "/logs/a.jsonl:3: not a JSON line"
    assert failed["status"] == "failed after 7 of 40 sessions"


def test_a_failure_without_a_reason_still_says_where_to_look(views):
    assert "service log" in views["failedNoReason"]["lede"]


def test_the_stage_polls_the_services_route_survives_a_lost_connection_and_then_reloads(views):
    driven = views["driven"]

    assert driven["urls"] == ["/mining/my%20repo/progress"] * 3
    assert driven["reloaded"] is True
    assert driven["headline"] == "Found 5 pain points in 40 sessions."
    assert driven["cells"] == 40 and driven["readCells"] == 40
    assert driven["startHidden"] == "none" and driven["repo"] == "my repo"
