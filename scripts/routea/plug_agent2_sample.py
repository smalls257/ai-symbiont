"""PLUG-AGENT-2 next-action sampler: one model call per (point, arm, seed), no containers.

The laptop Glimmer gets the history before the erroring turn, with the lesson's note appended
under the last message in the `note` arm; temperature 0.6 and the seed fix the sample, the same
seeds in both arms. Records the matcher's verdict only, never the prompt. Resumable.
Usage: plug_agent2_sample.py POINTS.json OUT.jsonl --seeds N
"""

import argparse
import json
import os
import urllib.request
from pathlib import Path

from minisweagent.models.utils.actions_toolcall import BASH_TOOL
from plug_agent2_nextaction import first_command, same_invocation, wire_history

from symbiont.delivery.mini_swe_wrapper import tagged

TEMPERATURE = 0.6
MAX_TOKENS = 4096


def request_body(history: list[dict], seed: int, model: str) -> dict:
    return {
        "model": model,
        "messages": history,
        "tools": [BASH_TOOL],
        "temperature": TEMPERATURE,
        "seed": seed,
        "max_tokens": MAX_TOKENS,
        "reasoning_effort": "low",
        "parallel_tool_calls": True,
    }


def sample(body: dict) -> dict:
    """One chat completion from the configured server (bearer key from the environment)."""
    url = os.environ["SYMBIONT_GLIMMER_URL"].rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(url, json.dumps(body).encode(), headers)
    with urllib.request.urlopen(request, timeout=900) as reply:  # noqa: S310 the configured server only
        return json.loads(reply.read())


def history_for(point: dict, arm: str) -> list[dict]:
    history = wire_history(json.loads(Path(point["messages_path"]).read_text())[: point["cut"]])
    if arm == "note":
        history[-1]["content"] = f"{history[-1]['content']}\n{tagged(point['note'])}"
    return history


def pending(points: list[dict], seeds: int, done: set) -> list[tuple[dict, str, int]]:
    """(point, arm, seed) still to sample, seeds outermost so both arms share each seed."""
    return [
        (point, arm, seed)
        for point in points
        for seed in range(1, seeds + 1)
        for arm in ("none", "note")
        if (point["id"], arm, seed) not in done
    ]


def sample_record(point: dict, arm: str, seed: int, model: str) -> dict:
    command = first_command(sample(request_body(history_for(point, arm), seed, model)))
    repeats = same_invocation(command, point["erroring_command"])
    return {
        "point": point["id"],
        "arm": arm,
        "seed": seed,
        "no_command": not command,
        "repeats": repeats,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("points", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--seeds", type=int, required=True)
    parser.add_argument("--model", default="Muse-Glimmer-30B-KQuant-17GB-Q4_K_M")
    args = parser.parse_args()
    lines = args.out.read_text().splitlines() if args.out.is_file() else []
    done = {(r["point"], r["arm"], r["seed"]) for r in map(json.loads, lines)}
    for point, arm, seed in pending(json.loads(args.points.read_text()), args.seeds, done):
        with args.out.open("a") as handle:
            handle.write(json.dumps(sample_record(point, arm, seed, args.model)) + "\n")


if __name__ == "__main__":
    main()
