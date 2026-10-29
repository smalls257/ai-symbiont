"""The verdict of the two-name Glimmer check, on hand-written results."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"
PLAIN_ARGS = ["llama-server", "--model", "base.gguf", "--parallel", "4"]
ADAPTER_ARGS = [
    "llama-server",
    "--model",
    "base.gguf",
    "--lora",
    "glimmer-sqlglot.gguf",
    "--parallel",
    "2",
]
GOOD = {"chat+tools": 3, "/completion": 3}
NONE = {"chat+tools": 0, "/completion": 0}


@pytest.fixture
def verify(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEB))
    spec = importlib.util.spec_from_file_location(
        "verify_glimmer_models", ROUTEB / "verify_glimmer_models.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("glimmer_chat", None)


def test_plain_without_lora_and_adapter_with_cards_passes(verify):
    assert verify.judge(NONE, GOOD, PLAIN_ARGS, ADAPTER_ARGS) == []


def test_a_card_from_the_plain_name_is_a_leak(verify):
    failures = verify.judge({"chat+tools": 1, "/completion": 0}, GOOD, PLAIN_ARGS, ADAPTER_ARGS)
    assert failures == ["plain answered with a lesson card on chat+tools (1x)"]


def test_a_plain_child_started_with_any_lora_fails_even_at_scale_0(verify):
    args = [*PLAIN_ARGS, "--lora", "x.gguf", "--lora-init-without-apply"]
    assert any(
        "plain child was started with a LoRA" in f
        for f in verify.judge(NONE, GOOD, args, ADAPTER_ARGS)
    )


def test_an_adapter_loaded_without_apply_or_without_cards_fails(verify):
    off = [*ADAPTER_ARGS, "--lora-init-without-apply"]
    assert any("scale 1" in f for f in verify.judge(NONE, GOOD, PLAIN_ARGS, off))
    weak = {"chat+tools": 1, "/completion": 3}
    assert verify.judge(NONE, weak, PLAIN_ARGS, ADAPTER_ARGS) == [
        "adapter gave a card on only 1/3 chat+tools answers"
    ]


def test_the_adapter_child_must_load_exactly_the_sqlglot_gguf_at_scale_1(verify):
    base = ["llama-server", "--model", "base.gguf"]
    assert verify.adapter_arg_problems([*base, "--lora", "glimmer-sqlglot.gguf"]) == []
    two = [*base, "--lora", "glimmer-sqlglot.gguf", "--lora", "glimmer-other.gguf"]
    assert any("2 --lora files" in p for p in verify.adapter_arg_problems(two))
    wrong = [*base, "--lora", "glimmer-freedoom.gguf"]
    assert any("not the sqlglot GGUF" in p for p in verify.adapter_arg_problems(wrong))
    loop = [*base, "--lora", "/serve/glimmer-freedoom-r2.gguf"]
    assert verify.adapter_arg_problems(loop, "glimmer-freedoom-r2.gguf") == []
    assert verify.adapter_arg_problems(loop, "glimmer-freedoom-r1.gguf")
    scaled = [*base, "--lora-scaled", "glimmer-sqlglot.gguf", "0.5"]
    problems = verify.adapter_arg_problems(scaled)
    assert any("0 --lora files" in p for p in problems) and any("scale 1" in p for p in problems)
    assert any("not exactly one" in p for p in verify.adapter_arg_problems([*base, "--lora"]))


def test_a_night_with_one_lesson_needs_its_one_card(verify):
    one = {"chat+tools": 1, "/completion": 1}
    assert verify.judge(NONE, one, PLAIN_ARGS, ADAPTER_ARGS, verify.Expectation(asked=1)) == []
    missed = verify.judge(NONE, NONE, PLAIN_ARGS, ADAPTER_ARGS, verify.Expectation(asked=1))
    assert "adapter gave a card on only 0/1 chat+tools answers" in missed
