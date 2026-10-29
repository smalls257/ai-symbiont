"""Train one Route B LoRA on bf16 Muse Glimmer 30B (HF transformers + peft on ROCm). GPU job.

Run only inside ops/gpu_run.sh. Every step appends a JSON line (loss, lr, seconds, memory) to the
log; a checkpoint every CHECKPOINT_EVERY steps makes a stopped run resumable; `.done` marks a
finished adapter. Exit 75 means the time cap stopped it at a checkpoint: rerun to resume.

Usage: python train_lora.py --snapshot S --train T --out DIR --log L [--max-minutes M] [--dry-run]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch
from glimmer_chat import row_ids
from lora_schedule import Budget, batch_order, lr_at, masked, padded
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import AutoConfig, AutoModelForImageTextToText, AutoTokenizer

# v/o and the MLP only: a q/k LoRA breaks llama.cpp's LoRA-to-GGUF conversion for this model
# (Q/K are un-permuted for RoPE there), and the GGUF adapter is how Glimmer serves it.
TARGETS = (
    r"model\.language_model\.layers\.\d+\."
    r"(self_attn\.(v_proj|o_proj)|mlp\.(gate_proj|up_proj|down_proj))"
)
RANK, ALPHA = 16, 32  # LCAP's rank 16 at scale 2
CHECKPOINT_EVERY = 100
SEED = 0
EXIT_TIME_CAP = 75


def _rows(tokenizer, train_file: Path) -> list[tuple[list[int], list[int]]]:
    rows = [json.loads(line) for line in train_file.read_text(encoding="utf-8").splitlines()]
    return [masked(*row_ids(tokenizer, row)) for row in rows]


def _model(snapshot: Path, resume: Path | None):
    base = AutoModelForImageTextToText.from_pretrained(
        snapshot, dtype=torch.bfloat16, device_map="cuda"
    )
    base.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    base.config.use_cache = False
    if resume is not None:
        return PeftModel.from_pretrained(base, resume, is_trainable=True)
    return get_peft_model(base, _lora_config())


def _lora_config() -> LoraConfig:
    return LoraConfig(
        r=RANK, lora_alpha=ALPHA, lora_dropout=0.0, target_modules=TARGETS, bias="none"
    )


def _memory() -> dict[str, float]:
    available_kb = next(
        int(line.split()[1])
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith("MemAvailable:")
    )
    return {
        "max_reserved_gb": round(torch.cuda.max_memory_reserved() / 1e9, 2),
        "mem_available_gb": round(available_kb / 1e6, 2),
    }


def _step(model, rows, pad_id: int) -> tuple[float, int]:
    ids, labels, mask = (torch.tensor(part, device="cuda") for part in padded(rows, pad_id))
    loss = model(input_ids=ids, attention_mask=mask, labels=labels).loss
    loss.backward()
    return loss.item(), int(mask.sum().item())


def _save(model, optimizer, out: Path, step: int) -> None:
    checkpoint = out / "checkpoint"
    model.save_pretrained(checkpoint)
    torch.save({"optimizer": optimizer.state_dict(), "step": step}, checkpoint / "trainer.pt")


def _resume_point(out: Path) -> tuple[Path | None, int, dict | None]:
    state_file = out / "checkpoint" / "trainer.pt"
    if not state_file.exists():
        return None, 0, None
    state = torch.load(state_file, map_location="cuda")
    return out / "checkpoint", state["step"], state["optimizer"]


class AdapterTraining:
    """One adapter's training: model, optimizer, step plan and where it logs."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args, self.budget = args, Budget()
        self.tokenizer = AutoTokenizer.from_pretrained(args.snapshot)
        self.rows = _rows(self.tokenizer, args.train)
        self.plan = batch_order(len(self.rows), self.budget, SEED)
        resume, self.start, optimizer_state = _resume_point(args.out)
        self.model = _model(args.snapshot, resume)
        trainable = [p for p in self.model.parameters() if p.requires_grad]
        self.optimizer = torch.optim.AdamW(trainable, lr=self.budget.floor_lr, weight_decay=0.0)
        if optimizer_state is not None:
            self.optimizer.load_state_dict(optimizer_state)
        self.pad_id = self.tokenizer.pad_token_id if self.tokenizer.pad_token_id is not None else 0
        self.trainable = sum(p.numel() for p in trainable)

    def one_step(self, step: int) -> dict[str, object]:
        """Run optimizer step `step` and return its log line."""
        lr = lr_at(step, len(self.plan), self.budget)
        for group in self.optimizer.param_groups:
            group["lr"] = lr
        started = time.monotonic()
        loss, tokens = _step(self.model, [self.rows[i] for i in self.plan[step]], self.pad_id)
        self.optimizer.step()
        self.optimizer.zero_grad(set_to_none=True)
        torch.cuda.synchronize()
        seconds = round(time.monotonic() - started, 2)
        return {
            "step": step,
            "loss": round(loss, 4),
            "lr": lr,
            "seconds": seconds,
            "tokens": tokens,
            **_memory(),
        }


def train(args: argparse.Namespace) -> int:
    """Train (or resume) to the end of the plan or the time cap; returns the exit code."""
    started, run = time.monotonic(), AdapterTraining(args)
    log = args.log.open("a", encoding="utf-8")
    header = {
        "event": "start",
        "rows": len(run.rows),
        "steps": len(run.plan),
        "from_step": run.start,
    }
    log.write(json.dumps({**header, "trainable_params": run.trainable}) + "\n")
    for step in range(run.start, len(run.plan)):
        log.write(json.dumps(run.one_step(step)) + "\n")
        log.flush()
        if (step + 1) % CHECKPOINT_EVERY == 0:
            _save(run.model, run.optimizer, args.out, step + 1)
            if args.max_minutes and time.monotonic() - started > args.max_minutes * 60:
                log.write(json.dumps({"event": "time cap", "next_step": step + 1}) + "\n")
                return EXIT_TIME_CAP
    run.model.save_pretrained(args.out)
    (args.out / ".done").touch()
    # LCAP's scorer reads peak memory from this line (bytes, the shape /usr/bin/time -l prints).
    print(f"{torch.cuda.max_memory_reserved()} peak memory footprint (torch max reserved)")
    return 0


def dry_run(args: argparse.Namespace) -> dict[str, int]:
    """CPU only: tokenize the set, plan the steps, attach the LoRA to a weightless skeleton."""
    rows = _rows(AutoTokenizer.from_pretrained(args.snapshot), args.train)
    config = AutoConfig.from_pretrained(args.snapshot)
    with torch.device("meta"):
        skeleton = AutoModelForImageTextToText.from_config(config, dtype=torch.bfloat16)
    lora = get_peft_model(skeleton, _lora_config())
    names = [name for name, _ in lora.named_modules() if name.endswith("lora_A")]
    return {
        "rows": len(rows),
        "steps": len(batch_order(len(rows), Budget(), SEED)),
        "lora_modules": len(names),
        "lora_layers": len({name.split(".layers.")[1].split(".")[0] for name in names}),
        "trainable_params": sum(p.numel() for p in lora.parameters() if p.requires_grad),
        "base_params": sum(p.numel() for p in skeleton.parameters()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--max-minutes", type=float, default=0.0, help="0: no cap")
    parser.add_argument("--dry-run", action="store_true", help="CPU check, no GPU, no weights")
    args = parser.parse_args()
    if args.dry_run:
        print(json.dumps(dry_run(args)))
        return
    if not torch.cuda.is_available():
        raise SystemExit("no GPU visible to torch: run inside ops/gpu_run.sh on the Strix")
    args.out.mkdir(parents=True, exist_ok=True)
    sys.exit(train(args))


if __name__ == "__main__":
    main()
