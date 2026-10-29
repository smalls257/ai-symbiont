"""Meta-learn a starting LoRA adapter across public repos with Reptile, or its joint-training twin.

Runs in the desktop LCAP venv. Multi-task training alone also teaches the answer format, so
`joint` trains one adapter on every meta-training row for the same steps and lr, and both are
judged on held-out repos. Logs iteration, inner loss and seconds every REPORT_EVERY iterations
(never row text); a non-finite loss stops the run.
Usage: meta_train_torch.py reptile|joint --model M --data DATA --out starts/NAME [...]
"""

import argparse
import json
import math
import time
from pathlib import Path

import torch
from meta_recipe import BATCH, INNER_LR, domain_order, interpolate, outer_step
from mlx_lora_recipe import batch_order
from train_lora_torch import (
    DEVICE,
    _chat,
    adam_update,
    batch_tensors,
    lora_model,
    masked_loss,
    peak_bytes,
)
from transformers import AutoTokenizer

REPORT_EVERY = 10
SEED = 0


def lora_params(model) -> dict[str, torch.Tensor]:
    return {name: p for name, p in model.named_parameters() if p.requires_grad}


def snapshot(model) -> dict[str, torch.Tensor]:
    """The LoRA weights as float32 copies: the outer update is done in full precision."""
    return {name: p.detach().float().clone() for name, p in lora_params(model).items()}


@torch.no_grad()
def load_weights(model, weights: dict[str, torch.Tensor]) -> None:
    """Copy `weights` into the model's LoRA parameters; raises KeyError on a name mismatch."""
    params = lora_params(model)
    if set(params) != set(weights):
        raise KeyError(f"{len(set(params) ^ set(weights))} LoRA names differ from the start file")
    for name, param in params.items():
        param.copy_(weights[name].to(param.dtype))


def encoded(tokenizer, messages: list[dict]) -> tuple[list[int], int]:
    """(tokens, offset of the assistant reply) for one chat row, as train_lora_torch encodes it."""
    tokens = _chat(tokenizer, messages, generation_prompt=False)
    return tokens, len(_chat(tokenizer, messages[:-1], generation_prompt=True))


def rows_by_repo(tokenizer, data: Path, repos: dict[str, list[str]]) -> dict[str, list]:
    """Encoded training rows of each repo, from rows.jsonl via each repo's lesson ids."""
    owner = {i: repo for repo, ids in repos.items() for i in ids}
    by_repo: dict[str, list] = {repo: [] for repo in repos}
    for line in (data / "rows.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["lesson_id"] in owner:
            by_repo[owner[row["lesson_id"]]].append(encoded(tokenizer, row["messages"]))
    return by_repo


def fit(model, rows: list, iters: int, *, seed: int, lr_at=lambda update: INNER_LR) -> float:
    """`iters` Adam updates (fresh moments) over `rows` in the recipe's batch order; mean loss."""
    params = list(lora_params(model).values())
    moments = [(torch.zeros_like(p), torch.zeros_like(p)) for p in params]
    lengths = [len(tokens) for tokens, _ in rows]
    total = 0.0
    for update, members in enumerate(batch_order(lengths, BATCH, iters, seed)):
        loss = masked_loss(model, *batch_tensors(rows, members, DEVICE))
        if not math.isfinite(loss.item()):
            raise FloatingPointError(f"loss {loss.item()} at update {update + 1}")
        loss.backward()
        adam_update(params, moments, lr_at(update))
        total += loss.item()
    return total / max(iters, 1)


def reptile(model, by_repo: dict[str, list], args) -> None:
    """Reptile: adapt to one repo for `inner_steps`, move the start toward the result, repeat."""
    start = snapshot(model)
    order = domain_order(sorted(by_repo), args.outer_iters, SEED)
    began, losses = time.monotonic(), []
    for iteration, repo in enumerate(order):
        load_weights(model, start)
        losses.append(fit(model, by_repo[repo], args.inner_steps, seed=iteration))
        step = outer_step(iteration, args.outer_iters, args.outer_step)
        adapted = snapshot(model)
        start = {name: interpolate(start[name], adapted[name], step) for name in start}
        if (iteration + 1) % REPORT_EVERY == 0 or iteration + 1 == args.outer_iters:
            mean = sum(losses) / len(losses)
            seconds = time.monotonic() - began
            print(
                f"outer {iteration + 1} inner_loss {mean:.4f} step {step:.3f} s {seconds:.0f}",
                flush=True,
            )
            losses = []
    load_weights(model, start)


def joint(model, by_repo: dict[str, list], args) -> None:
    """One adapter on every meta-training row, same lr, same total updates as the Reptile run."""
    rows = [row for repo in sorted(by_repo) for row in by_repo[repo]]
    began = time.monotonic()
    loss = fit(model, rows, args.iters, seed=SEED)
    print(
        f"joint iters {args.iters} mean_loss {loss:.4f} s {time.monotonic() - began:.0f}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="method", required=True)
    for name in ("reptile", "joint"):
        one = sub.add_parser(name)
        one.add_argument("--model", required=True)
        one.add_argument("--data", type=Path, required=True)
        one.add_argument("--out", type=Path, required=True)
    sub.choices["reptile"].add_argument("--inner-steps", type=int, required=True)
    sub.choices["reptile"].add_argument("--outer-iters", type=int, required=True)
    sub.choices["reptile"].add_argument("--outer-step", type=float, required=True)
    sub.choices["joint"].add_argument("--iters", type=int, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    train = json.loads((args.data / "domains.json").read_text())["train"]
    by_repo = rows_by_repo(tokenizer, args.data, train)
    model = lora_model(args.model)
    {"reptile": reptile, "joint": joint}[args.method](model, by_repo, args)
    args.out.mkdir(parents=True, exist_ok=True)
    torch.save(snapshot(model), args.out / "start.pt")
    print(f"{peak_bytes()} peak memory footprint", flush=True)


if __name__ == "__main__":
    main()
