"""Train one LCAP LoRA adapter on a CUDA GPU with transformers + peft, on the laptop's MLX recipe.

Runs in the desktop LCAP venv. Everything mlx-lm 0.32.2 decides is copied (`mlx_lora_recipe`) so 3B
and 1B rows stay comparable. `--recipe nightly` uses train_lora.sh's short warmup and `--resume DIR`
continues from a saved adapter with fresh Adam moments. Logs never carry row text; a non-finite loss
stops the run.
Usage: venv/bin/python train_lora_torch.py --model M --data train/one-10 --iters 120 --adapter out/
"""

import argparse
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

import torch
from mlx_lora_recipe import WARMUP, batch_order, learning_rate, loss_span, padded_width, warmup_for
from peft import LoraConfig, get_peft_model, set_peft_model_state_dict
from safetensors.torch import load_file
from torch.nn.functional import cross_entropy
from transformers import AutoModelForCausalLM, AutoTokenizer

RANK = 16
SCALE = 2.0  # run_lcap.sh lora_parameters.scale; peft spells it lora_alpha / r
BATCH = 4
SEED = 0
BETAS = (0.9, 0.999)
EPS = 1e-8
REPORT_EVERY = 20
# Every linear layer inside each decoder block: what mlx-lm picks with num_layers -1 and no keys.
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
# mlx-lm built training prompts without a date_string, so the Llama template stamped the day the
# laptop trained (2026-10-28); pinning that day gives the same tokens and reproducible reruns.
TRAIN_DATE = "28 Oct 2026"
# "cuda" on the desktop; "mps" runs the same code on the laptop's Apple GPU (METALORA).
DEVICE = os.environ.get("LCAP_DEVICE", "cuda")


def peak_allocated_bytes() -> int:
    """Peak GPU memory in live tensors: what must fit, apart from allocator caching."""
    if DEVICE == "mps":
        return torch.mps.current_allocated_memory()
    return torch.cuda.max_memory_allocated()


def peak_bytes() -> int:
    """Peak GPU memory reserved by this process, on CUDA or Apple MPS."""
    if DEVICE == "mps":
        return torch.mps.driver_allocated_memory()
    return torch.cuda.max_memory_reserved()


def encoded_rows(tokenizer, path: Path) -> list[tuple[list[int], int]]:
    """(tokens, offset of the assistant reply) per row, as mlx-lm ChatDataset with mask_prompt."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        messages = json.loads(line)["messages"]
        tokens = _chat(tokenizer, messages, generation_prompt=False)
        offset = len(_chat(tokenizer, messages[:-1], generation_prompt=True))
        rows.append((tokens, offset))
    return rows


def _chat(tokenizer, messages: list[dict], *, generation_prompt: bool) -> list[int]:
    return tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=generation_prompt,
        date_string=TRAIN_DATE,
        tokenize=True,
        return_dict=False,
    )


def batch_tensors(rows: list[tuple[list[int], int]], members: list[int], device: str):
    """Zero-padded token array and its loss mask for one batch, as mlx-lm builds them."""
    width = padded_width([len(rows[i][0]) for i in members])
    ids = torch.zeros((len(members), width), dtype=torch.long)
    mask = torch.zeros((len(members), width - 1), dtype=torch.float32)
    for slot, index in enumerate(members):
        tokens, offset = rows[index]
        length = min(len(tokens), width)
        ids[slot, :length] = torch.tensor(tokens[:length])
        span = loss_span(offset, length, width)
        mask[slot, span.start : span.stop] = 1.0
    return ids.to(device), mask.to(device)


def lora_model(model_path: str, seed: int = SEED):
    model = AutoModelForCausalLM.from_pretrained(model_path, dtype=torch.bfloat16).to(DEVICE)
    torch.manual_seed(seed)
    config = LoraConfig(
        r=RANK, lora_alpha=RANK * SCALE, lora_dropout=0.0, target_modules=TARGETS, bias="none"
    )
    return get_peft_model(model, config)


def resume_from(model, adapter_dir: Path) -> None:
    """Load a saved PEFT adapter into the model's LoRA weights. Raises on missing or extra keys,
    so a start from the wrong rank or model never trains silently from random weights."""
    state = load_file(adapter_dir / "adapter_model.safetensors")
    result = set_peft_model_state_dict(model, state)
    if result.unexpected_keys:
        raise KeyError(f"{len(result.unexpected_keys)} adapter weights match no LoRA layer")
    lora_names = {n for n, p in model.named_parameters() if p.requires_grad}
    if len(state) != len(lora_names):
        raise KeyError(
            f"adapter has {len(state)} tensors, model has {len(lora_names)} LoRA weights"
        )


def masked_loss(model, ids: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Mean cross-entropy over masked targets (mlx default_loss); projects only those positions."""
    hidden = model.base_model.model.model(input_ids=ids[:, :-1]).last_hidden_state
    picked = mask.bool()
    logits = model.base_model.model.lm_head(hidden[picked]).float()
    losses = cross_entropy(logits, ids[:, 1:][picked], reduction="sum")
    return losses / mask.sum()


@torch.no_grad()
def adam_update(params: list[torch.Tensor], moments: list[tuple], lr: float) -> None:
    """mlx.optimizers.Adam with bias_correction=False: p -= lr * m / (sqrt(v) + eps)."""
    for param, (first, second) in zip(params, moments, strict=True):
        grad = param.grad
        first.mul_(BETAS[0]).add_(grad, alpha=1 - BETAS[0])
        second.mul_(BETAS[1]).addcmul_(grad, grad, value=1 - BETAS[1])
        param.sub_(lr * first / (second.sqrt() + EPS))
        param.grad = None


@dataclass(frozen=True)
class Schedule:
    """The recipe's warmup and a factor on its learning rate (1.0: the recipe unchanged)."""

    warmup: int = WARMUP
    lr_scale: float = 1.0


def train(
    model, rows: list[tuple[list[int], int]], iters: int, schedule: Schedule, seed: int = SEED
) -> None:
    params = [p for p in model.parameters() if p.requires_grad]
    moments = [(torch.zeros_like(p), torch.zeros_like(p)) for p in params]
    lengths = [len(tokens) for tokens, _ in rows]
    started, losses = time.monotonic(), []
    for update, members in enumerate(batch_order(lengths, BATCH, iters, seed)):
        loss = masked_loss(model, *batch_tensors(rows, members, DEVICE))
        if not math.isfinite(loss.item()):
            raise FloatingPointError(f"loss {loss.item()} at iter {update + 1}")
        loss.backward()
        lr = learning_rate(update, iters, schedule.warmup) * schedule.lr_scale
        adam_update(params, moments, lr)
        losses.append(loss.item())
        if (update + 1) % REPORT_EVERY == 0 or update + 1 == iters:
            mean, seconds = sum(losses) / len(losses), time.monotonic() - started
            print(f"iter {update + 1} loss {mean:.4f} lr {lr:.2e} s {seconds:.0f}", flush=True)
            losses = []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", type=Path, required=True, help="dir holding train.jsonl")
    parser.add_argument("--iters", type=int, required=True)
    parser.add_argument("--adapter", type=Path, required=True, help="output dir")
    parser.add_argument("--resume", type=Path, help="adapter dir to continue from")
    parser.add_argument("--seed", type=int, default=SEED, help="batch order and LoRA init")
    parser.add_argument("--recipe", choices=("lcap", "nightly"), default="lcap")
    # Round 4's 3B retry: the recipe's schedule times this factor; 1.0 is the recipe unchanged.
    parser.add_argument("--lr-scale", type=float, default=1.0)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    rows = encoded_rows(tokenizer, args.data / "train.jsonl")
    model = lora_model(args.model, args.seed)
    if args.resume:
        resume_from(model, args.resume)
    model.print_trainable_parameters()
    warmup = warmup_for(args.iters) if args.recipe == "nightly" else WARMUP
    train(model, rows, args.iters, Schedule(warmup, args.lr_scale), args.seed)
    model.save_pretrained(args.adapter)
    # same words as macOS `time -l`, so score_answers.py reads GPU peak memory unchanged
    print(f"{peak_allocated_bytes()} peak allocated")
    print(f"{peak_bytes()} peak memory footprint")


if __name__ == "__main__":
    main()
