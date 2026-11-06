"""The keyless demo runs end to end with no API key and says the notes the product would say.

Guarded: a demo that exits 0 while printing nothing a viewer came to see.
The demo starts a real service on loopback, so the test is periphery; the child gets no key.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.periphery

DEMO = Path(__file__).resolve().parents[2] / "scripts" / "demo" / "keyless_demo.py"
TIMEOUT_S = 240


@pytest.fixture(scope="module")
def walkthrough():
    env = {k: v for k, v in os.environ.items() if k != "META_API_KEY"}
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(DEMO)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=TIMEOUT_S,
        check=False,
    )


def test_the_demo_finishes_cleanly_without_a_key(walkthrough):
    assert walkthrough.returncode == 0, walkthrough.stdout + walkthrough.stderr
    assert "== Summary" in walkthrough.stdout


def test_the_house_rules_note_carries_both_corrections(walkthrough):
    out = walkthrough.stdout
    assert "House rules for this repo" in out
    assert "every ledger entry gets an audit.record call" in out
    assert "convert a fee at today's rate, not the stored rate" in out


def test_the_repeated_failure_gets_a_recall_note_and_why_explains_it(walkthrough):
    out = walkthrough.stdout
    assert "Last time, `pytest` failed with AssertionError" in out
    assert "It fired because" in out


def test_the_onboarding_note_comes_before_allow_and_mining_reports_its_lessons(walkthrough):
    out = walkthrough.stdout
    assert out.index("not switched on for this repository") < out.index("symbiont repo allow")
    assert "learned 1 lesson from 1 Claude Code session" in out
    assert "dashboard: http://127.0.0.1:" in out
