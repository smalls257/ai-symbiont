"""Train one LCAP LoRA adapter on a CUDA GPU with transformers + peft, on the laptop's MLX recipe.

Runs in the desktop LCAP venv (torch, transformers, peft), not the repo env. Violation prevented:
**Paper Tiger**. A port that trained differently would make the 3B rows incomparable with the
1B rows, so everything mlx-lm 0.32.2 decides is copied: LoRA on every linear layer of every block
(rank 16, scale 2 = alpha 32, no dropout), plain Adam without bias correction (mlx's default),
the warmup-plus-cosine lr, the length-sorted batch order and the prompt-masked loss
(`mlx_lora_recipe`). It logs loss, lr and seconds every 20 iters and peak GPU memory at the end,
never row text; a non-finite loss stops the run (**Silent Fallback** guard).

    venv/bin/python train_lora_torch.py --model M --data train/one-10 --iters 120 --adapter out/
"""

import argparse
import json
import math
import os
import time
from pathlib import Path

import torch
from mlx_lora_recipe import batch_order, learning_rate, loss_span, padded_width
from peft import LoraConfig, get_peft_model
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


def lora_model(model_path: str):
    model = AutoModelForCausalLM.from_pretrained(model_path, dtype=torch.bfloat16).to(DEVICE)
    torch.manual_seed(SEED)
    config = LoraConfig(
        r=RANK, lora_alpha=RANK * SCALE, lora_dropout=0.0, target_modules=TARGETS, bias="none"
    )
    return get_peft_model(model, config)


def masked_loss(model, ids: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Mean cross-entropy over the masked target tokens of the whole batch (mlx default_loss)."""
    logits = model(input_ids=ids[:, :-1]).logits.float()
    losses = cross_entropy(logits.transpose(1, 2), ids[:, 1:], reduction="none")
    return (losses * mask).sum() / mask.sum()


@torch.no_grad()
def adam_update(params: list[torch.Tensor], moments: list[tuple], lr: float) -> None:
    """mlx.optimizers.Adam with bias_correction=False: p -= lr * m / (sqrt(v) + eps)."""
    for param, (first, second) in zip(params, moments, strict=True):
        grad = param.grad
        first.mul_(BETAS[0]).add_(grad, alpha=1 - BETAS[0])
        second.mul_(BETAS[1]).addcmul_(grad, grad, value=1 - BETAS[1])
        param.sub_(lr * first / (second.sqrt() + EPS))
        param.grad = None


def train(model, rows: list[tuple[list[int], int]], iters: int) -> None:
    params = [p for p in model.parameters() if p.requires_grad]
    moments = [(torch.zeros_like(p), torch.zeros_like(p)) for p in params]
    lengths = [len(tokens) for tokens, _ in rows]
    started, losses = time.monotonic(), []
    for update, members in enumerate(batch_order(lengths, BATCH, iters, SEED)):
        loss = masked_loss(model, *batch_tensors(rows, members, DEVICE))
        if not math.isfinite(loss.item()):
            raise FloatingPointError(f"loss {loss.item()} at iter {update + 1}")
        loss.backward()
        lr = learning_rate(update, iters)
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
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    rows = encoded_rows(tokenizer, args.data / "train.jsonl")
    model = lora_model(args.model)
    model.print_trainable_parameters()
    train(model, rows, args.iters)
    model.save_pretrained(args.adapter)
    # same words as macOS `time -l`, so score_answers.py reads GPU peak memory unchanged
    print(f"{peak_bytes()} peak memory footprint")


if __name__ == "__main__":
    main()
