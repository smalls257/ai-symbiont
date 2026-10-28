"""Reasoning-strength go/no-go: plain Glimmer at low vs high on 20 Freedoom and 10 coding items.

Violation prevented: Paper Tiger. A learned chooser of reasoning strength is only worth building
if low is nearly as good as high, much cheaper, and this holds on some items and not others; this
script measures exactly that, one request at a time, under the frozen rule in
prereg/2026-10-28-reasoning-strength-gate.md.

Usage: run_reasoning_gate.py [--smoke] [--workdir DIR] [--out FILE]
Needs SYMBIONT_GLIMMER_URL. --smoke runs 2 items per arm into the workdir, never into results/.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from gate_client import ask
from gate_coding import GoldStep, proposal_matches, proposal_names_file
from gate_doom import DoomOracle, score_doom_reply
from gate_items import load_or_build_items
from gate_requests import request_for
from gate_results import build_results
from gate_verdict import ItemOutcome

from symbiont.act1.glimmer import Reply

progress = logging.getLogger("reasoning_gate")
GLIMMER_URL_VAR = "SYMBIONT_GLIMMER_URL"  # the address is never committed
STRENGTHS = ("low", "high")
SMOKE_ITEMS = 2


def glimmer_url() -> str:
    url = os.environ.get(GLIMMER_URL_VAR)
    if not url:
        raise SystemExit(f"{GLIMMER_URL_VAR} is not set: export the Glimmer endpoint (env.example)")
    return url


def arm_order(index: int) -> tuple[str, str]:
    """Alternate which arm goes first, so slow drift on the machine does not favor one arm."""
    return STRENGTHS if index % 2 == 0 else STRENGTHS[::-1]


def read_done(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {(r["item_id"], r["strength"]): r for r in rows}


def run_arms(workdir: Path, items: list[dict[str, Any]], log_path: Path) -> None:
    """Every item under both arms, one request at a time, appended to the replies log."""
    url, done = glimmer_url(), read_done(log_path)
    for index, item in enumerate(items):
        for strength in arm_order(index):
            if (item["item_id"], strength) in done:
                continue
            messages, tools = request_for(workdir, item, strength)
            completion = ask(url, messages, tools)
            row = {"item_id": item["item_id"], "strength": strength, **completion.__dict__}
            with log_path.open("a") as log:
                log.write(json.dumps(row) + "\n")
            progress.info(
                "%s %s %s tokens=%d %.0fs", item["item_id"], strength, completion.finish_reason,
                completion.completion_tokens, completion.seconds,
            )  # fmt: skip


def label_for(item: dict[str, Any], row: dict[str, Any]) -> str:
    """Scored label: success, or why not (wrong_move, invalid, truncated, wrong_file, no_action)."""
    if item["domain"] == "freedoom":
        oracle = DoomOracle(
            item["oracle_kind"],
            frozenset(item["go_to_targets"]),
            frozenset(item["walk_to_targets"]),
        )
        return score_doom_reply(
            Reply(row["text"], row["finish_reason"], row["reasoning_chars"]), oracle
        )
    gold = GoldStep(item["gold_index"], item["gold_path"], frozenset(item["gold_functions"]))
    if row["finish_reason"] == "length":
        return "truncated"
    if row["command"] is None:
        return "no_action"
    return "success" if proposal_matches(row["command"], gold) else "wrong_file_or_function"


def file_only_hit(item: dict[str, Any], row: dict[str, Any]) -> bool:
    """Secondary coding reading: same file, whatever the function. Not in the decision rule."""
    gold = GoldStep(item["gold_index"], item["gold_path"], frozenset(item["gold_functions"]))
    return item["domain"] == "coding" and proposal_names_file(row["command"], gold)


def outcomes_from(items: list[dict[str, Any]], done: dict[tuple[str, str], dict[str, Any]]):
    """Per-item outcomes plus the labels, for the items whose both arms have a reply."""
    scored = []
    for item in items:
        low, high = done.get((item["item_id"], "low")), done.get((item["item_id"], "high"))
        if low is None or high is None:
            continue
        labels = {"low": label_for(item, low), "high": label_for(item, high)}
        ok = {arm: labels[arm] == "success" for arm in STRENGTHS}
        outcome = ItemOutcome(
            item["item_id"], item["domain"], ok["low"], ok["high"],
            low["completion_tokens"], high["completion_tokens"], low["seconds"], high["seconds"],
        )  # fmt: skip
        scored.append((outcome, labels, file_only_hit(item, low), file_only_hit(item, high)))
    return scored


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--workdir", type=Path, default=Path("data/reasoning-gate"))
    parser.add_argument("--out", type=Path, default=Path("results/reasoning-strength-gate.json"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    items = load_or_build_items(args.workdir)
    if args.smoke:
        items = [items[0], items[-1]][:SMOKE_ITEMS]
    log_path = args.workdir / ("replies-smoke.jsonl" if args.smoke else "replies.jsonl")
    run_arms(args.workdir, items, log_path)
    scored = outcomes_from(items, read_done(log_path))
    target = args.workdir / "smoke-results.json" if args.smoke else args.out
    target.write_text(
        json.dumps(build_results(scored, "smoke" if args.smoke else "full"), indent=1) + "\n"
    )
    progress.info("wrote %s", target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
