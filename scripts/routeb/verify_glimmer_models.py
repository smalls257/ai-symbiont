"""Verify the two Glimmer names on the router: plain has no adapter, the sqlglot name has it.

Checks each child's launch args (plain: no --lora at all; adapter: --lora at scale 1), then asks
held-out sqlglot questions on both paths open-webui and mini-SWE-agent use (chat with tools) and
the raw /completion path. A lesson card in any plain answer is a leak and fails the run.

Usage: python verify_glimmer_models.py --server U --snapshot S --work W [--plain N] [--system F]
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from glimmer_chat import prompt_ids
from glimmer_hosts import require_glimmer_server

CARD = "What happened:"  # how every trained lesson card opens; plain Glimmer never says it
QUESTIONS = 3
MIN_ADAPTER_CARDS = 2  # of QUESTIONS, per path
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command in the repository.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }
]


def _post(server: str, path: str, payload: dict) -> dict:
    request = Request(
        f"{server}{path}", json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    with urlopen(request, timeout=600) as response:
        return json.loads(response.read())


def chat_text(server: str, model: str, system: str, question: str) -> str:
    """Everything the chat-with-tools path returns: answer, reasoning and tool-call arguments."""
    reply = _post(
        server,
        "/v1/chat/completions",
        {
            "model": model,
            "temperature": 0.0,
            "max_tokens": 400,
            "tools": TOOLS,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
        },
    )
    message = reply["choices"][0]["message"]
    calls = [call["function"].get("arguments", "") for call in message.get("tool_calls") or []]
    return " ".join([message.get("content") or "", message.get("reasoning_content") or "", *calls])


def completion_text(server: str, model: str, ids: list[int]) -> str:
    """The raw /completion path, with no lora field at all."""
    reply = _post(
        server, "/completion", {"model": model, "prompt": ids, "n_predict": 160, "temperature": 0.0}
    )
    return reply["content"]


def child_args(server: str, model: str) -> list[str]:
    """The launch args the router gave `model`'s child; raises if the model is not listed."""
    with urlopen(f"{server}/models", timeout=30) as response:
        listed = {m["id"]: m for m in json.loads(response.read())["data"]}
    if model not in listed:
        raise LookupError(f"{model} is not listed by the router")
    status = listed[model].get("status")
    return status.get("args", []) if isinstance(status, dict) else []


def adapter_arg_problems(args: list[str]) -> list[str]:
    """What is wrong with the adapter child's LoRA flags; empty for one sqlglot GGUF at scale 1."""
    loras = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "--lora"]
    problems = []
    if len(loras) != 1:
        problems.append(f"adapter child loads {len(loras)} --lora files, not exactly one")
    if any(not (Path(p).suffix == ".gguf" and "sqlglot" in Path(p).name) for p in loras):
        problems.append(f"adapter child's --lora is not the sqlglot GGUF: {loras}")
    if "--lora-scaled" in args or "--lora-init-without-apply" in args:
        problems.append("adapter child is not started with --lora at scale 1")
    return problems


def judge(
    plain_cards: dict[str, int],
    adapter_cards: dict[str, int],
    plain_args,
    adapter_args,
    asked: int = QUESTIONS,
) -> list[str]:
    """Every failed check, in words; empty when both names behave.

    `asked` is how many questions each path got (a night with one new lesson asks one), so the
    adapter needs MIN_ADAPTER_CARDS cards, or every answer when fewer were asked.
    """
    needed = min(MIN_ADAPTER_CARDS, asked)
    failures = []
    if any(arg.startswith("--lora") for arg in plain_args):
        failures.append(
            f"plain child was started with a LoRA: {[a for a in plain_args if 'lora' in a]}"
        )
    failures += adapter_arg_problems(list(adapter_args))
    failures += [
        f"plain answered with a lesson card on {path} ({n}x)"
        for path, n in plain_cards.items()
        if n
    ]
    failures += [
        f"adapter gave a card on only {n}/{asked} {path} answers"
        for path, n in adapter_cards.items()
        if n < needed
    ]
    return failures


def cards_for(
    server: str, model: str, tokenizer, system: str, questions: list[dict]
) -> dict[str, int]:
    """How many answers carry a lesson card, per path."""
    chat = [chat_text(server, model, system, q["text"]) for q in questions]
    raw = [
        completion_text(
            server,
            model,
            prompt_ids(
                tokenizer,
                [{"role": "system", "content": system}, {"role": "user", "content": q["text"]}],
            ),
        )
        for q in questions
    ]
    return {"chat+tools": sum(CARD in t for t in chat), "/completion": sum(CARD in t for t in raw)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--plain", default="Muse-Glimmer-30B-KQuant-17GB-Q4_K_M")
    parser.add_argument("--adapter", default="Muse-Glimmer-30B-sqlglot")
    parser.add_argument(
        "--system",
        type=Path,
        help="the memory turn the adapter was trained under (the nightly job writes one per repo); "
        "default: the sqlglot adapter's",
    )
    args = parser.parse_args()
    require_glimmer_server(args.server)
    from sqlglot_rows import MEMORY_SYSTEM
    from transformers import AutoTokenizer

    system = args.system.read_text(encoding="utf-8") if args.system else MEMORY_SYSTEM

    tokenizer = AutoTokenizer.from_pretrained(args.snapshot)
    lines = (args.work / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    questions = [json.loads(line) for line in lines[:QUESTIONS]]
    if not questions:
        sys.exit(f"verify_glimmer_models: no questions in {args.work / 'questions.jsonl'}")
    plain = cards_for(args.server, args.plain, tokenizer, system, questions)
    adapter = cards_for(args.server, args.adapter, tokenizer, system, questions)
    failures = judge(
        plain,
        adapter,
        child_args(args.server, args.plain),
        child_args(args.server, args.adapter),
        asked=len(questions),
    )
    print(
        json.dumps({"plain_cards": plain, "adapter_cards": adapter, "failures": failures}, indent=1)
    )
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
