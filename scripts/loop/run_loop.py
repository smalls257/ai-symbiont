"""Run rounds of the recursive learning loop, or print what a real round would do and cost.

`dry-run` and `compare-starts` use the simulated domain and fake learners (no Glimmer, no GPU);
`plan` prints a real domain's steps and hours; `round` runs one real round, only with `--go`.
State lives under --state outside the repo; stdout carries counts, ids and labels only.
Usage: uv run python scripts/loop/run_loop.py dry-run --rounds 3 [--route R] [--start S]
Usage: uv run python scripts/loop/run_loop.py compare-starts --rounds 4 [--route R]
Usage: uv run python scripts/loop/run_loop.py plan --domain coding-sqlglot|freedoom
Usage: uv run python scripts/loop/run_loop.py round --domain D --config F --state DIR --go
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import estimate
from fake_domain import SHARED_HABITS, WARNER_DELIVERY, FakeDomain
from learners import FakeLearner, Route, Start
from ledger import Ledger, curve, ledger_path, save
from round_runner import LoopSettings, RoundContext, run_round
from training_plan import TrainMode

EXIT_REFUSED = 64


@dataclass(frozen=True)
class DryRun:
    """One simulated loop: how many rounds, which route and start, how adapters are trained."""

    rounds: int
    route: Route = Route.GLIMMER_ADAPTER
    start: Start = Start.PLAIN
    mode: TrainMode = TrainMode.FROM_SCRATCH


def dry_run(plan: DryRun, state: Path, say: Callable[[str], None] = print) -> dict:
    """`plan.rounds` simulated rounds; returns the publishable curve and the last utility table."""
    learned: dict[str, frozenset[str]] = {}
    delivery = 1.0 if plan.route is Route.GLIMMER_ADAPTER else WARNER_DELIVERY
    domain = FakeDomain(learned, delivery=delivery)
    learner = FakeLearner(plan.route, plan.start, learned, SHARED_HABITS, domain.plain_model, say)
    ledger = Ledger.declare(domain.name, domain.held_out(), str(plan.route), str(plan.start))
    if ledger_path(state, ledger.key).exists():
        raise SystemExit(f"{state} already holds {ledger.key}; a dry run starts from nothing")
    context = RoundContext(domain, learner, ledger, LoopSettings(train_mode=plan.mode), say)
    for _ in range(plan.rounds):
        say(f"--- round {ledger.next_round} ({plan.route}, start {plan.start}; simulated)")
        run_round(context)
        save(state, ledger)
    return {
        "curve": curve(ledger),
        "last_utility": ledger.rounds[-1]["utility"],
        "retired": sorted(ledger.retired),
    }


def compare_starts(rounds: int, route: Route, state: Path) -> dict:
    """The same simulated loop from each start: learning to learn, side by side."""
    found = {}
    for start in Start:
        result = dry_run(DryRun(rounds, route, start), state, say=lambda _line: None)
        found[str(start)] = {
            "learning_speed": result["curve"]["learning_speed"],
            "held_out_by_round": [
                (r["start_passed"], r["adapter_passed"], r["adapter_graded"])
                for r in result["curve"]["rounds"]
            ],
        }
    return {"label": "stand-in: simulated domain, no model", "route": str(route), **found}


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    dry = sub.add_parser("dry-run")
    dry.add_argument("--rounds", type=int, default=3)
    dry.add_argument("--state", type=Path, help="default: a fresh temporary directory")
    dry.add_argument("--train-mode", type=TrainMode, default=TrainMode.FROM_SCRATCH)
    dry.add_argument("--route", type=Route, default=Route.GLIMMER_ADAPTER)
    dry.add_argument("--start", type=Start, default=Start.PLAIN)
    both = sub.add_parser("compare-starts")
    both.add_argument("--rounds", type=int, default=4)
    both.add_argument("--route", type=Route, default=Route.GLIMMER_ADAPTER)
    both.add_argument("--state", type=Path, help="default: a fresh temporary directory")
    plan = sub.add_parser("plan")
    plan.add_argument("--domain", choices=sorted(estimate.DOMAINS), required=True)
    real = sub.add_parser("round")
    real.add_argument("--domain", choices=sorted(estimate.DOMAINS), required=True)
    real.add_argument("--config", type=Path, required=True)
    real.add_argument("--state", type=Path, required=True)
    real.add_argument("--go", action="store_true", help="the owner's go for one real round")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Dispatch the subcommand; a real round without --go is refused."""
    args = _arguments(argv)
    if args.command in ("dry-run", "compare-starts"):
        state = args.state or Path(tempfile.mkdtemp(prefix="symbiont-loop-"))
        if args.command == "dry-run":
            plan = DryRun(args.rounds, args.route, args.start, args.train_mode)
            print(json.dumps(dry_run(plan, state), indent=1))
        else:
            print(json.dumps(compare_starts(args.rounds, args.route, state), indent=1))
        print(f"ledger: {state}")
        return 0
    if args.command == "plan":
        print(json.dumps(estimate.round_plan(args.domain), indent=1))
        return 0
    if not args.go:
        print(
            "run_loop: a real round needs the owner's --go (Glimmer and GPU time)", file=sys.stderr
        )
        return EXIT_REFUSED
    from real_round import run_real_round

    return run_real_round(args.domain, args.config, args.state)


if __name__ == "__main__":
    sys.exit(main())
