"""The live judge demo fails loudly without a key and promises only what the repo can deliver.

A live demo whose recall never fires on the real failure, or one that starts a session without a
key, passes a smoke test and fails the judge.
Nothing here starts Muse or touches the network; the end-to-end run is manual (it needs a key).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

DEMO_DIR = Path(__file__).resolve().parents[2] / "scripts" / "demo"
sys.path.insert(0, str(DEMO_DIR))
import ledger_session as session  # noqa: E402
import live  # noqa: E402

from symbiont.core.failure_signature import same_failure  # noqa: E402

LEDGER = DEMO_DIR.parents[1] / "examples" / "ledger"


def test_a_missing_key_stops_with_the_command_that_fixes_it():
    with pytest.raises(SystemExit) as stopped:
        live.require_key({})
    assert "META_API_KEY" in str(stopped.value)
    assert "docker run -it --rm -e META_API_KEY=... ai-symbiont live" in str(stopped.value)


def test_a_blank_key_counts_as_missing():
    with pytest.raises(SystemExit):
        live.require_key({"META_API_KEY": "  "})


def test_a_key_is_returned_untouched():
    assert live.require_key({"META_API_KEY": "abc"}) == "abc"


def test_outside_the_image_the_demo_refuses_to_touch_the_machine():
    with pytest.raises(SystemExit, match="Docker image"):
        live.require_container({})
    live.require_container({"SYMBIONT_DEMO_IN_DOCKER": "1"})


def test_the_live_script_exits_nonzero_without_a_key_before_any_setup():
    env = {k: v for k, v in os.environ.items() if k != "META_API_KEY"}
    done = subprocess.run(
        [sys.executable, str(DEMO_DIR / "live.py")],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode != 0
    assert "META_API_KEY is not set" in done.stderr
    assert "setting up" not in done.stdout


def test_the_entrypoint_routes_live_and_keeps_demo_and_passthrough():
    script = (DEMO_DIR / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert '"live" ]' in script and "scripts/demo/live.py" in script
    assert "scripts/demo/keyless_demo.py" in script
    assert script.rstrip().endswith('exec "$@"')


def test_the_card_names_the_house_rules_and_the_failing_command_it_will_recall():
    card = live.CARD
    assert all(rule in card for rule in session.CORRECTIONS)
    assert session.FAILING_TEST in card


def test_the_failure_a_judge_really_gets_matches_the_one_the_history_recalls():
    """Drift between the real pytest report and the hand-written history silences the recall."""
    ran = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-k", "refund", "-p", "no:cacheprovider"],
        cwd=LEDGER, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert ran.returncode == 1, ran.stdout + ran.stderr
    assert same_failure(ran.stdout, session.FAILURE_TEXT[-240:])
