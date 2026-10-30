"""Core D2 W arm: most-similar earlier tasks by word overlap, trimmed to a budget."""

import importlib.util
from pathlib import Path

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"
spec = importlib.util.spec_from_file_location(
    "core2_worked_examples", ROUTEB / "core2_worked_examples.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_the_two_closest_issues_win_and_ties_break_by_id():
    earlier = [
        {"instance_id": "b", "problem_statement": "parse error in the sql tokenizer"},
        {"instance_id": "a", "problem_statement": "parse error in the sql tokenizer"},
        {"instance_id": "c", "problem_statement": "unrelated color theme"},
        {"instance_id": "d", "problem_statement": "tokenizer parse"},
    ]
    picked = module.most_similar("sql tokenizer parse error", earlier)
    assert [r["instance_id"] for r in picked] == ["a", "b"]
    assert module.similarity("", "x") == 0.0


def test_steps_are_cut_to_the_budget_and_results_are_shortened():
    messages = [{"role": "system", "content": "skip me"},
                {"role": "assistant", "content": "ls"},
                {"role": "user", "content": "x" * 1000}]  # fmt: skip
    text = module.render_steps(messages, 10_000)
    assert "skip me" not in text and text.count("x") == module.RESULT_CHARS
    assert module.render_steps(messages, 1) == ""  # the first part already overruns the budget


def test_the_block_names_both_examples_and_ends_with_the_task_cue():
    first = {"instance_id": "e1", "problem_statement": "issue one"}
    rows = [(first, [{"role": "assistant", "content": "ls"}]),
            ({"instance_id": "e2", "problem_statement": "issue two"}, [])]  # fmt: skip
    block = module.example_block(rows)
    assert "Example 1: e1" in block and "Example 2: e2" in block
    assert block.endswith("Now solve this issue:\n\n")
