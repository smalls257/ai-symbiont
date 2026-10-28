"""Run plain Glimmer at low and high reasoning strength on the 30 gate items."""

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
from symbiont.eval.prereg_git import run_provenance

progress = logging.getLogger("reasoning_gate")
GLIMMER_URL_VAR = "SYMBIONT_GLIMMER_URL"  # the address is never committed
STRENGTHS = ("low", "high")
SMOKE_ITEMS = 2
PREREG_NAME = "2026-10-28-reasoning-strength-gate.md"  # the original the amendments amend


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
    done = read_done(log_path)
    url: str | None = None  # read only when a request is needed, so a resume needs no endpoint
    for index, item in enumerate(items):
        for strength in arm_order(index):
            if (item["item_id"], strength) in done:
                continue
            url = url or glimmer_url()
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
    if item["domain"] != "coding":
        return False
    gold = GoldStep(item["gold_index"], item["gold_path"], frozenset(item["gold_functions"]))
    return proposal_names_file(row["command"], gold)


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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="2 items per arm, into the workdir")
    parser.add_argument("--scored", action="store_true", help="a scored run: needs --prereg")
    parser.add_argument("--prereg", help="the frozen amendment file this run is held to")
    parser.add_argument("--workdir", type=Path, default=Path("data/reasoning-gate"))
    parser.add_argument("--out", type=Path, default=Path("results/reasoning-strength-gate.json"))
    return parser.parse_args(argv)


def output_path(args: argparse.Namespace) -> Path:
    """results/ takes scored runs only; anything else lands in the workdir."""
    if args.smoke:
        return args.workdir / "smoke-results.json"
    return args.out if args.scored else args.workdir / "exploratory-results.json"


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    provenance = run_provenance(
        scored=args.scored and not args.smoke, prereg=args.prereg, expects=PREREG_NAME
    )
    items = load_or_build_items(args.workdir)
    if args.smoke:
        items = [items[0], items[-1]][:SMOKE_ITEMS]
    log_path = args.workdir / ("replies-smoke.jsonl" if args.smoke else "replies.jsonl")
    run_arms(args.workdir, items, log_path)
    scored = outcomes_from(items, read_done(log_path))
    document = build_results(scored, "smoke" if args.smoke else "full", provenance)
    target = output_path(args)
    target.write_text(json.dumps(document, indent=1) + "\n")
    progress.info("wrote %s", target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
