"""`symbiont nightly setup`: build the judge kit from a base the user downloaded and a small kit.

Meta's license forbids shipping the merged weights, so the user downloads the base from Meta and
the small public kit by hand; this module checks both, then merges locally. It makes no network
call, so the egress policy is untouched, and a wrong file is a named `KitSetupError`.
"""

import hashlib
import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from symbiont.service.nightly_kit import BASE, BASE_MARKER, GENERAL_ROWS, HABITS, read_rows
from symbiont.service.nightly_run import Runner

BASE_MODEL = "meta-llama/Llama-3.2-1B-Instruct"
KIT_URL = "https://huggingface.co/smalls257/Llama-3.2-1B-symbiont-judge-adapters"
KIT_REPO = KIT_URL.removeprefix("https://huggingface.co/")
KIT_FOLDER = "nightly-kit"
ADAPTER_FILE = "adapter_model.safetensors"
ADAPTER_CONFIG = "adapter_config.json"
WORK = ".setup-work"
# What a Llama 3.2 1B config says. Instruct and base share it; the chat template tells them apart.
BASE_SHAPE = {"model_type": "llama", "hidden_size": 2048, "num_hidden_layers": 16}
BASE_VOCAB = 128256
TORCH_PROBE = "import torch, peft, transformers"

# Stage 1 merges judge-s0 into the base; stage 2 merges the general adapter into that result,
# because round 4 trained `general` on top of the judge-s0 merge (the HF README says so).
MERGE_STAGES = ("judge-s0", "general")
# sha256 of every kit file, pinned so a changed or truncated download fails here and not after a
# night of training. Provenance of the two jsonl files is in the HF README and the PR.
KIT_PINS = {
    "judge-s0/adapter_model.safetensors": (
        "6375047268eb3e285d21b4632a5661ced347c1aa319ec47ed0ba57c77e0d7bdc"
    ),
    "general/adapter_model.safetensors": (
        "9dd0422fd53df8e6bac98db972a88e002f5ad28180d25dfd312790e12204a863"
    ),
    GENERAL_ROWS: "271ae3baeb05e7658aee229efe5ddad09f1f4ce432691e3b13d0897898e31c21",
    HABITS: "4d9f3947375996d594fd57f37edc6d08c2d4c87ee8f2ff7d69abf85bd61adf20",
}
KIT_PLAIN_FILES = ("judge-s0/" + ADAPTER_CONFIG, "general/" + ADAPTER_CONFIG)
DOWNLOAD_BASE = (
    f"accept Meta's license on https://huggingface.co/{BASE_MODEL}, log in with "
    f"`huggingface-cli login`, then run `huggingface-cli download {BASE_MODEL} "
    "--local-dir <folder>` and pass that folder as --base"
)
DOWNLOAD_KIT = (
    f"run `huggingface-cli download {KIT_REPO} --include '{KIT_FOLDER}/*' "
    f"--local-dir <folder>` and pass <folder>/{KIT_FOLDER} as --kit-files"
)


class KitSetupError(RuntimeError):
    """A file is missing, wrong or damaged, or the merge failed; the message says what to do."""


@dataclass(frozen=True)
class SetupInputs:
    """What the user supplies and where the kit goes."""

    base: Path
    kit_files: Path
    kit_dir: Path
    merge_python: str


def check_base(base: Path) -> None:
    """Raise KitSetupError unless `base` is a Llama 3.2 1B Instruct folder with weights."""
    config = _read_json(base / BASE_MARKER, f"the base model folder {base}", DOWNLOAD_BASE)
    shape = {key: config.get(key) for key in BASE_SHAPE}
    if shape != BASE_SHAPE or config.get("vocab_size") != BASE_VOCAB:
        raise KitSetupError(
            f"{base} is not Llama 3.2 1B (its config says {shape}, vocab "
            f"{config.get('vocab_size')}); {DOWNLOAD_BASE}"
        )
    missing = [name for name in ("tokenizer.json",) if not (base / name).is_file()]
    if not any(base.glob("*.safetensors")):
        missing.append("model.safetensors")
    if missing:
        raise KitSetupError(f"{base} lacks {', '.join(missing)}; {DOWNLOAD_BASE}")
    if not _has_chat_template(base):
        raise KitSetupError(
            f"{base} has no chat template, so it is the plain base model, not the Instruct "
            f"one; {DOWNLOAD_BASE}"
        )


def _has_chat_template(base: Path) -> bool:
    """Instruct ships a chat template (a file or in tokenizer_config.json); the base has none."""
    if (base / "chat_template.jinja").is_file():
        return True
    settings = _read_json(
        base / "tokenizer_config.json", f"{base}/tokenizer_config.json", DOWNLOAD_BASE
    )
    return bool(settings.get("chat_template"))


def _read_json(path: Path, what: str, remedy: str) -> dict:
    """The JSON object in `path`; raises KitSetupError naming `what` and the `remedy`."""
    if not path.is_file():
        raise KitSetupError(f"{what} is missing {path.name}; {remedy}")
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as unreadable:
        raise KitSetupError(f"{path} is not valid JSON ({unreadable}); {remedy}") from unreadable
    if not isinstance(found, dict):
        raise KitSetupError(f"{path} is not a JSON object; {remedy}")
    return found


def sha256_of(path: Path) -> str:
    """Hex SHA-256 of a file, read in 1 MiB pieces."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for piece in iter(lambda: handle.read(1 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def check_kit_files(files: Path) -> None:
    """Raise KitSetupError unless every kit file is present, intact and well-formed."""
    absent = [name for name in (*KIT_PINS, *KIT_PLAIN_FILES) if not (files / name).is_file()]
    if absent:
        raise KitSetupError(f"{files} lacks {', '.join(absent)}; {DOWNLOAD_KIT}")
    for name, pinned in KIT_PINS.items():
        if sha256_of(files / name) != pinned:
            raise KitSetupError(f"{files / name} does not match the published kit; {DOWNLOAD_KIT}")
    for rows in (GENERAL_ROWS, HABITS):
        read_rows(files / rows)


def check_merge_python(python: str, run: Runner, log: Path) -> None:
    """Raise KitSetupError unless `python` can import torch, peft and transformers."""
    if run(python, ["-c", TORCH_PROBE], log, {}) != 0:
        raise KitSetupError(
            f"{python} cannot import torch, peft and transformers (see {log}); the merge needs "
            "them. Install them into that Python or pass another with --judge-python"
        )


def merge_kit(inputs: SetupInputs, run: Runner, script: Path, say: Callable[[str], None]) -> None:
    """Merge both adapters into the base, then install `base/` and the two row files.

    Raises KitSetupError if a merge exits non-zero; the work folder is kept for its log.
    """
    work = inputs.kit_dir / WORK
    work.mkdir(parents=True, exist_ok=True)
    source = inputs.base
    for index, stage in enumerate(MERGE_STAGES):
        out = work / f"merged-{index}"
        say(f"merging {stage} into the base (stage {index + 1} of {len(MERGE_STAGES)})")
        args = _merge_args(script, source, inputs.kit_files / stage, out)
        if run(inputs.merge_python, args, work / f"merge-{stage}.log", {}) != 0:
            raise KitSetupError(f"merging {stage} failed; see {work / f'merge-{stage}.log'}")
        source = out
    _install(inputs, source, work)


def _merge_args(script: Path, model: Path, adapter: Path, out: Path) -> Sequence[str]:
    return [str(script), "--model", str(model), "--adapter", str(adapter), "--out", str(out)]


def _install(inputs: SetupInputs, merged: Path, work: Path) -> None:
    """Move the merged base into place and copy the replay files; then drop the work folder."""
    for rows in (GENERAL_ROWS, HABITS):
        shutil.copyfile(inputs.kit_files / rows, inputs.kit_dir / rows)
    target = inputs.kit_dir / BASE
    if target.exists():
        shutil.rmtree(target)
    merged.replace(target)
    shutil.rmtree(work)
