"""The reasoning-strength gate: verdict rule, step finding, scoring and the results shape."""

import json
import sys
from pathlib import Path

import pytest

EXPERIMENTS = Path(__file__).resolve().parents[2] / "scripts" / "experiments"
sys.path.insert(0, str(EXPERIMENTS))

import gate_coding as coding  # noqa: E402  (needs the path above)
import gate_doom as doom  # noqa: E402
import gate_results  # noqa: E402
import gate_verdict as verdict  # noqa: E402

from symbiont.act1.env_text import GameStateView, Layout, RouteHint, SeenDoor, SeenExit  # noqa: E402
from symbiont.act1.glimmer import Reply  # noqa: E402

PATCH = (
    "diff --git a/pkg/parser.py b/pkg/parser.py\n--- a/pkg/parser.py\n+++ b/pkg/parser.py\n"
    "@@ -10,3 +10,4 @@ def parse_args(x)\n+    def helper_two(self):\n"
)


def call(command):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "bash", "arguments": json.dumps({"command": command})}}
        ],
    }


def outcome(name, low_ok, high_ok, low_tokens, high_tokens):
    return verdict.ItemOutcome(name, "coding", low_ok, high_ok, low_tokens, high_tokens, 1.0, 2.0)


def test_patch_functions_come_from_hunk_headers_and_added_lines():
    assert coding.patched_functions(PATCH) == {
        "pkg/parser.py": frozenset({"parse_args", "helper_two"})
    }


def test_gold_step_is_the_first_edit_of_a_patched_file_after_exploration():
    messages = [{"role": "system", "content": "s"}]
    messages += [call("ls"), call("cat pkg/parser.py"), call("grep x pkg/parser.py")]
    messages += [call("sed -i 's/a/b/' /tmp/parser.py"), call("sed -i 's/a/b/' pkg/parser.py")]
    gold = coding.find_gold_step(messages, PATCH)
    assert (gold.message_index, gold.path) == (5, "pkg/parser.py")


def test_no_edit_of_a_patched_file_raises():
    with pytest.raises(coding.NoGoldStepError):
        coding.find_gold_step([call("ls")] * 6, PATCH)


def test_proposal_needs_the_file_and_one_known_function():
    gold = coding.GoldStep(5, "pkg/parser.py", frozenset({"parse_args"}))
    assert coding.proposal_matches("sed -n '1,20p' pkg/parser.py  # parse_args", gold)
    assert not coding.proposal_matches("cat pkg/parser.py", gold)
    assert not coding.proposal_matches("cat pkg/tokens.py parse_args", gold)
    assert coding.proposal_names_file("cat parser.py", gold)
    assert not coding.proposal_matches(None, gold)


def view(**fields):
    base = dict(
        health=100, ammo=50, position=(0, 0), angle_deg=0, objects=(), doors=(), keys_held=(),
        layout=Layout(True, True, True, False),
    )  # fmt: skip
    return GameStateView(**{**base, **fields})


def hints(*pairs):
    return tuple(
        RouteHint(kind, label, dist, 0, None if dist else "blocked") for kind, label, dist in pairs
    )


def test_oracle_prefers_exit_then_key_then_door():
    exit_state = view(routes=hints(("exit", "exit", 90.0), ("key", "RedCard", 10.0)))
    assert doom.oracle_for(exit_state).kind == "exit"
    key_state = view(routes=hints(("exit", "exit", None), ("key", "RedCard", 10.0)))
    assert doom.oracle_for(key_state).go_to_targets == frozenset({"key", "redcard"})
    door_state = view(routes=hints(("door", "door", 5.0)), doors=(SeenDoor(5.0, 0.0),))
    assert doom.oracle_for(door_state).walk_to_targets == frozenset({"door"})
    assert doom.oracle_for(view(routes=hints(("exit", "exit", None)))) is None


def test_walk_to_counts_only_for_things_in_view():
    seen = view(routes=hints(("exit", "exit", 9.0)), exits=(SeenExit(False, 9.0, 0.0),))
    assert doom.oracle_for(seen).walk_to_targets == frozenset({"exit"})
    assert doom.oracle_for(view(routes=hints(("exit", "exit", 9.0)))).walk_to_targets == frozenset()


@pytest.mark.parametrize(
    ("text", "finish", "label"),
    [
        ("go_to(exit)", "stop", "success"),
        ("go_to(door)\ngo_to(exit)", "stop", "wrong_move"),
        ("explore()", "stop", "invalid"),
        ("go_to(exit)", "length", "truncated"),
        ("walk_to(exit)", "stop", "wrong_move"),
    ],
)
def test_doom_reply_labels(text, finish, label):
    oracle = doom.DoomOracle("exit", frozenset({"exit"}), frozenset())
    assert doom.score_doom_reply(Reply(text, finish, 0), oracle) == label


def test_verdict_is_go_only_when_all_three_conditions_hold():
    even = [outcome(f"a{i}", True, True, 100, 400) for i in range(7)]
    pricey = [outcome(f"b{i}", True, True, 320, 400) for i in range(3)]  # ratio 0.8 vs median 0.25
    assert verdict.decide(even + pricey)["verdict"] == "GO"
    assert verdict.decide(even)["verdict"] == "NO-GO"  # nothing differs: uniform answer
    lost = [outcome(f"e{i}", False, True, 100, 400) for i in range(3)]
    assert verdict.decide(even + lost)["conditions"]["success_within_10_points"] is False
    costly = [outcome(f"c{i}", True, True, 300, 400) for i in range(10)]
    assert verdict.decide(costly)["conditions"]["median_token_ratio_at_most_half"] is False
    worse = [outcome(f"d{i}", i < 7, True, 100, 400) for i in range(10)]
    assert verdict.decide(worse)["conditions"]["success_within_10_points"] is False


def test_zero_token_arm_is_refused_not_scored():
    with pytest.raises(ValueError, match="no completion tokens"):
        verdict.decide([outcome("x", True, True, 0, 100)])


def test_results_document_has_reference_rows_and_passes_the_content_shape():
    scored = [
        (outcome("i1", True, True, 100, 400), {"low": "success", "high": "success"}, True, True),
        (
            outcome("i2", False, True, 120, 400),
            {"low": "wrong_move", "high": "success"},
            False,
            True,
        ),
    ]
    document = gate_results.build_results(scored, "full")
    roles = {row["arm"]: row["role"] for row in document["rows"]}
    assert roles == {
        "fixed_low": "reference",
        "fixed_high": "reference",
        "hindsight_chooser": "ceiling",
    }
    assert document["rows"][0]["per_item"] == "10"
    assert document["decision"]["verdict"] in {"GO", "NO-GO"}
    sys.path.insert(0, str(EXPERIMENTS.parent / "gates"))
    import check_results_content as content

    assert content.findings_in("doc.json", document) == []
