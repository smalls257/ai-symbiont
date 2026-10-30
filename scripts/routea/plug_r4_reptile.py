"""Plug round 4, Reptile meta-training of the judge's LoRA over mined repo-nights (exploratory).

Usage (desktop venv): python plug_r4_reptile.py --model BASE --tasks DIR --replay R --out DIR \
Usage:   --steps 300 --stop-at EPOCH_SECONDS

Each meta-step adapts the shared LoRA weights on a few repositories' repeat rows and moves them
toward the adapted weights (Reptile). Checkpoints every 25 steps; resumes; stops at a hard deadline.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import torch
from train_lora_torch import (
    BATCH,
    DEVICE,
    adam_update,
    batch_tensors,
    encoded_rows,
    lora_model,
    masked_loss,
    resume_from,
)
from transformers import AutoTokenizer

CHECKPOINT_EVERY = 25
MIN_ROWS = 8  # a repository with fewer repeat rows is not a task


def params_of(model) -> list[torch.Tensor]:
    return [p for p in model.parameters() if p.requires_grad]


def adapt(model, rows: list, steps: int, lr: float, rng: random.Random) -> None:
    """`steps` Adam steps (fresh moments, constant rate) on random batches of the task's rows."""
    params = params_of(model)
    moments = [(torch.zeros_like(p), torch.zeros_like(p)) for p in params]
    for _ in range(steps):
        members = rng.sample(range(len(rows)), min(BATCH, len(rows)))
        loss = masked_loss(model, *batch_tensors(rows, members, DEVICE))
        loss.backward()
        adam_update(params, moments, lr)


def meta_step(model, theta: list, pools: tuple, args, rng: random.Random) -> None:
    """One Reptile update: the mean move toward each drawn task's adapted weights."""
    tasks, replay = pools
    params = params_of(model)
    moved = [torch.zeros_like(t) for t in theta]
    drawn = rng.sample(tasks, min(args.meta_batch, len(tasks)))
    for rows in drawn:
        with torch.no_grad():
            for p, t in zip(params, theta, strict=True):
                p.copy_(t)
        support = rows + rng.sample(replay, max(1, len(rows) // 4))
        adapt(model, support, args.inner, args.lr, rng)
        with torch.no_grad():
            for m, p, t in zip(moved, params, theta, strict=True):
                m.add_(p - t)
    with torch.no_grad():
        for t, m in zip(theta, moved, strict=True):
            t.add_(m, alpha=args.epsilon / len(drawn))


def save_checkpoint(model, theta: list, out: Path, step: int) -> None:
    """Write the shared weights as a PEFT adapter, then record the step (state last)."""
    with torch.no_grad():
        for p, t in zip(params_of(model), theta, strict=True):
            p.copy_(t)
    folder = out / f"ckpt-{step:03d}"
    model.save_pretrained(folder)
    (out / "state.json").write_text(json.dumps({"step": step, "ckpt": folder.name}))


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", type=Path, required=True, help="dir of per-repo rows files")
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--inner", type=int, default=8)
    parser.add_argument("--meta-batch", type=int, default=4)
    parser.add_argument("--epsilon", type=float, default=0.5)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--stop-at", type=float, required=True, help="epoch seconds, hard stop")
    return parser.parse_args()


def load_tasks(tokenizer, directory: Path) -> list:
    """One encoded row list per repository with enough rows; archive metadata files are skipped."""
    found = [
        encoded_rows(tokenizer, p)
        for p in sorted(directory.glob("*.jsonl"))
        if not p.name.startswith(".")
    ]
    return [rows for rows in found if len(rows) >= MIN_ROWS]


def resumed_step(model, out: Path) -> int:
    """Load the last checkpoint if there is one; the step it was saved at (0 if none)."""
    state = out / "state.json"
    if not state.exists():
        return 0
    last = json.loads(state.read_text())
    resume_from(model, out / last["ckpt"])
    return last["step"]


def main() -> None:
    args = arguments()
    args.out.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    tasks = load_tasks(tokenizer, args.tasks)
    replay = encoded_rows(tokenizer, args.replay)
    model = lora_model(args.model)
    state = args.out / "state.json"
    step = resumed_step(model, args.out)
    theta = [p.detach().clone() for p in params_of(model)]
    rng = random.Random(f"reptile:{step}")
    print(f"tasks={len(tasks)} start_step={step}", flush=True)
    started = time.monotonic()
    while step < args.steps and time.time() < args.stop_at:
        meta_step(model, theta, (tasks, replay), args, rng)
        step += 1
        if step % CHECKPOINT_EVERY == 0 or step == args.steps:
            save_checkpoint(model, theta, args.out, step)
            print(f"step {step} s {time.monotonic() - started:.0f}", flush=True)
    if state.exists() is False or json.loads(state.read_text())["step"] != step:
        save_checkpoint(model, theta, args.out, step)
    (args.out / "DONE").write_text(f"step {step} of {args.steps}\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
