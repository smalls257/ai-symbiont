"""Maintainer tool: stage the four published adapters for a Hugging Face upload.

The nightly adapters are withheld pending a terms check. Adapters only.

Copies `adapter_model.safetensors` and a sanitized `adapter_config.json` (the base model is named
by its public id, never a local path), writes LICENSE, NOTICE and the model card, and refuses to
stage anything else. No tokenizer, no merged weights, no training data.
Usage: uv run python scripts/reproduce/stage_adapters.py --runs DIR --out DIR
"""

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_ID = "meta-llama/Llama-3.2-1B-Instruct"
LICENSE_URL = (
    "https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama3_2/LICENSE"
)
LICENSE_SHA256 = "8cc15535a8a34b41888f644b339a1a9eb428af793a4f5e24df58a3e5b1487d74"
NOTICE = (
    "Llama 3.2 is licensed under the Llama 3.2 Community License, "
    "Copyright (c) Meta Platforms, Inc. All Rights Reserved.\n"
)
SOURCES = {
    "judge-s0": "aidev/plug-r3-run/adapters/judge-s0",
    "judge-s1": "aidev/plug-r3-run/adapters/judge-s1",
    "judge-s2": "aidev/plug-r3-run/adapters/judge-s2",
    "general": "smith-local/r4c/explore/general-adapter",
}
ALLOWED = frozenset({"adapter_config.json", "adapter_model.safetensors"})


class LicenseTextError(RuntimeError):
    """The downloaded license text is not the one this tool was written against."""


def sanitized_config(source: Path) -> str:
    """The adapter config with its base model named by public id; other fields untouched."""
    config = json.loads(source.read_text())
    config["base_model_name_or_path"] = BASE_ID
    return json.dumps(config, indent=2, sort_keys=True) + "\n"


def stage_adapter(source: Path, target: Path) -> None:
    """Copy one adapter's two files; the config is sanitized on the way."""
    target.mkdir(parents=True)
    shutil.copy(source / "adapter_model.safetensors", target / "adapter_model.safetensors")
    (target / "adapter_config.json").write_text(sanitized_config(source / "adapter_config.json"))


def license_text() -> bytes:
    """Meta's license text, refused unless it is byte for byte the pinned one."""
    with urllib.request.urlopen(LICENSE_URL, timeout=30) as reply:  # noqa: S310 - fixed https URL
        text = reply.read()
    if hashlib.sha256(text).hexdigest() != LICENSE_SHA256:
        raise LicenseTextError(f"{LICENSE_URL} no longer matches sha256 {LICENSE_SHA256}")
    return text


def staged_files(out: Path) -> list[Path]:
    """Every file under `out`, relative."""
    return sorted(path.relative_to(out) for path in out.rglob("*") if path.is_file())


def refuse_extras(out: Path) -> None:
    """Raise SystemExit if anything other than adapters, card, license and notice is staged."""
    top = {"LICENSE", "NOTICE", "README.md", "pins.json"}
    for path in staged_files(out):
        if len(path.parts) == 1 and path.name in top:
            continue
        if len(path.parts) == 2 and path.name in ALLOWED:
            continue
        raise SystemExit(f"refusing to stage {path}")


def main() -> int:
    """Stage everything under --out and print the pins for results/repro-adapter-pins.json."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    for name, relative in SOURCES.items():
        stage_adapter(args.runs / relative, args.out / name)
    (args.out / "LICENSE").write_bytes(license_text())
    (args.out / "NOTICE").write_text(NOTICE)
    shutil.copy(HERE / "adapter_card.md", args.out / "README.md")
    pins = {
        name: {
            file: hashlib.sha256((args.out / name / file).read_bytes()).hexdigest()
            for file in sorted(ALLOWED)
        }
        for name in SOURCES
    }
    (args.out / "pins.json").write_text(json.dumps(pins, indent=1) + "\n")
    refuse_extras(args.out)
    sys.stdout.write(json.dumps(pins, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
