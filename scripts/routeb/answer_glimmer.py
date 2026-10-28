"""Answer Route B held-out questions with Glimmer on a local llama-server, one arm per call.

Prompts are Glimmer's own template as token ids, so the server answers exactly what the adapter was
trained on. Every adapter the server holds is named with its scale in every request (the arm's at
1, the rest at 0). Writes LCAP's answer rows; stderr gets counts and seconds, never text.

Usage: answer_glimmer.py --server U --snapshot S --questions Q --system F --out A --adapters K
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

from glimmer_chat import prompt_ids
from transformers import AutoTokenizer

MAX_TOKENS = 96  # LCAP's answer cap; answers are cut at the first newline
PARALLEL = 4  # matches the server's --parallel slots
TIMEOUT_S = 600


def _payload(ids: list[int], lora_scales: list[float]) -> dict[str, object]:
    return {
        "prompt": ids,
        "n_predict": MAX_TOKENS,
        "temperature": 0.0,
        "stop": ["\n"],
        "cache_prompt": True,
        "lora": [{"id": index, "scale": scale} for index, scale in enumerate(lora_scales)],
    }


def complete(server: str, ids: list[int], lora_scales: list[float]) -> str:
    """One greedy completion; raises on any HTTP or server error rather than answering ''."""
    body = json.dumps(_payload(ids, lora_scales)).encode()
    request = Request(f"{server}/completion", body, {"Content-Type": "application/json"})
    with urlopen(request, timeout=TIMEOUT_S) as response:
        reply = json.loads(response.read())
    if "content" not in reply:
        raise RuntimeError(f"server reply has no content (keys: {sorted(reply)})")
    stripped = reply["content"].strip()
    return stripped.splitlines()[0] if stripped else ""


def lora_scales(adapters: int, chosen: int | None) -> list[float]:
    """Scale 1 for the chosen adapter, 0 for every other one; all 0 for the floor and ceiling."""
    if chosen is not None and not 0 <= chosen < adapters:
        raise ValueError(f"adapter {chosen} is not among the server's {adapters}")
    return [1.0 if index == chosen else 0.0 for index in range(adapters)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--server", "--snapshot", "--questions", "--system", "--out"):
        parser.add_argument(flag, required=True)
    parser.add_argument("--adapters", type=int, required=True, help="adapters the server holds")
    parser.add_argument("--lora", type=int, help="index of the adapter to apply; none: base model")
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.snapshot)
    system = Path(args.system).read_text(encoding="utf-8")
    questions = [json.loads(line) for line in Path(args.questions).read_text().splitlines()]
    prompts = [
        prompt_ids(
            tokenizer,
            [{"role": "system", "content": system}, {"role": "user", "content": q["text"]}],
        )
        for q in questions
    ]
    scales, started = lora_scales(args.adapters, args.lora), time.monotonic()
    with ThreadPoolExecutor(PARALLEL) as pool:
        answers = list(pool.map(lambda ids: complete(args.server, ids, scales), prompts))
    with Path(args.out).open("w", encoding="utf-8") as fh:
        for question, answer in zip(questions, answers, strict=True):
            fh.write(json.dumps({"question_id": question["question_id"], "answer": answer}) + "\n")
    empty, seconds = sum(1 for answer in answers if not answer), time.monotonic() - started
    print(f"answered={len(answers)} empty={empty} seconds={seconds:.1f}", file=sys.stderr)


if __name__ == "__main__":
    main()
