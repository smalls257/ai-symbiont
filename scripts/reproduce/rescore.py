"""Tier 3 `rescore`: score the 924 items with the published round 3 judge and decide.

Needs a Python with torch, transformers and peft (SYMBIONT_TORCH_PYTHON), the Llama-3.2-1B-Instruct
base from Meta, and the published adapters at the pinned revision. Only the judge arms (judge
alone, agree rule) can be rescored: the nightly adapters are withheld. LCAP_DEVICE picks mps or
cuda (default cuda).
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTEA = ROOT / "scripts" / "routea"
RESULTS = ROOT / "results"
SEEDS = (0, 1, 2)
EXIT_MISSING_PREREQUISITE = 3


class AdapterPinError(RuntimeError):
    """An adapter file does not hash to its pin, or the pins name no published revision yet."""


def adapter_pins() -> dict:
    """The committed adapter pins: repository id, revision and each file's SHA-256."""
    return json.loads((RESULTS / "repro-adapter-pins.json").read_text())


def verify_adapters(adapters: Path, pins: dict) -> None:
    """Raise AdapterPinError naming the first adapter file that is missing or differs."""
    for name, files in pins["adapters"].items():
        for file, wanted in files.items():
            path = adapters / name / file
            if not path.exists():
                raise AdapterPinError(f"missing {name}/{file}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != wanted:
                raise AdapterPinError(f"{name}/{file} differs from its pin")


def adapter_repo(chosen: str | None, pins: dict) -> str:
    """The Hugging Face repository: the flag, else SYMBIONT_ADAPTER_REPO, else the pins."""
    named = chosen or os.environ.get("SYMBIONT_ADAPTER_REPO") or pins.get("repo_id")
    if not named:
        raise AdapterPinError(
            f"name the model repository: --repo {ADAPTER_REPO_URL} or set SYMBIONT_ADAPTER_REPO"
        )
    return repo_id_of(named)


# The owner's handle may appear in tracked files only inside a public URL (QG-SEC-05), so the
# repository is written as its URL and reduced to the "owner/name" id the hub client expects.
ADAPTER_REPO_URL = "https://huggingface.co/smalls257/Llama-3.2-1B-symbiont-judge-adapters"
_HUB_PREFIXES = ("https://huggingface.co/", "http://huggingface.co/", "huggingface.co/", "hf.co/")


def repo_id_of(named: str) -> str:
    """'owner/name' from either the id or a huggingface.co / hf.co URL of it."""
    for prefix in _HUB_PREFIXES:
        if named.startswith(prefix):
            return named.removeprefix(prefix).strip("/")
    return named


def fetch_adapters(dest: Path, repo: str | None = None) -> None:
    """Download the published adapters at the pinned revision and verify every file."""
    pins = adapter_pins()
    if not pins.get("revision"):
        raise AdapterPinError("the adapters are not published yet: no revision in the pins")
    from huggingface_hub import snapshot_download  # noqa: PLC0415 - only this step needs it

    snapshot_download(adapter_repo(repo, pins), revision=pins["revision"], local_dir=dest)
    verify_adapters(dest, pins)


def torch_python() -> str:
    """The interpreter that has torch, transformers and peft."""
    return os.environ.get("SYMBIONT_TORCH_PYTHON", sys.executable)


def torch_step(script: str, *words: str) -> None:
    """Run one of the study's torch scripts; a failure stops the stage."""
    done = subprocess.run([torch_python(), str(ROUTEA / script), *words], check=False)
    if done.returncode != 0:
        raise SystemExit(f"FAIL: {script} exited {done.returncode}")


def announce(line: str) -> None:
    """One progress line."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def score_judges(items: Path, base: Path, adapters: Path, work: Path) -> None:
    """Three round 3 judge seeds on every query, each applied on the plain base."""
    out = work / "out"
    out.mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        announce(f"score: judge seed {seed}")
        torch_step(
            "score_pairs_torch.py",
            "--model",
            str(base),
            "--adapter",
            str(adapters / f"judge-s{seed}"),
            "-q",
            str(items / "primary-queries.jsonl"),
            "-o",
            str(out / f"primary-judge-s{seed}.jsonl"),
        )


def decide_judges(items: Path, adapters: Path, work: Path) -> Path:
    """The study's frozen rule for the judge alone and the agree rule; returns the decision file."""
    sys.path[:0] = [str(ROOT / "src"), str(ROUTEA)]
    from plug_r4_combine import candidates, decide, judge_top, two_d_rules  # noqa: PLC0415
    from plug_r4_combo import merged_candidates  # noqa: PLC0415
    from plug_r4_scored import (  # noqa: PLC0415
        FROZEN_JUDGE_THRESHOLD,
        SHORTLIST,
        read_scores,
        summarize,  # noqa: PLC0415
    )
    from plug_r4_smith_decide import check  # noqa: PLC0415
    from plug_situation import item_from  # noqa: PLC0415
    from warm_start import _read_jsonl  # noqa: PLC0415

    selections = [RESULTS / "plug-r4-selection.json", RESULTS / "plug-r4-selection-nightly.json"]
    check(items, adapters, selections, RESULTS / "plug-r4-smith-pins.json")
    records = _read_jsonl(items / "primary-items.jsonl")
    entries = [item_from(r) for r in records]
    cluster = {r["question_id"]: r["task"] for r in records}
    scores = read_scores(work / "out", items / "primary-queries.jsonl")
    cands = merged_candidates(entries, candidates(entries, scores))
    chosen = json.loads(selections[0].read_text())
    alone = decide(entries, cands, judge_top(SHORTLIST), FROZEN_JUDGE_THRESHOLD)
    agree = decide(entries, cands, two_d_rules()[chosen["rule"]], chosen["threshold"])
    out = work / "decision.json"
    found = {"agree_vs_judge_alone": summarize(entries, cluster, alone, agree, agree)}
    out.write_text(json.dumps(found, indent=1) + "\n")
    return out


def rescore(items: Path, base: Path, adapters: Path, work: Path) -> Path:
    """Verify, score, decide; returns the decision file and prints the elapsed time."""
    started = time.monotonic()
    work.mkdir(parents=True, exist_ok=True)
    verify_adapters(adapters, adapter_pins())
    score_judges(items, base, adapters, work)
    out = decide_judges(items, adapters, work)
    announce(f"rescored in {time.monotonic() - started:.0f}s: {out}")
    return out
