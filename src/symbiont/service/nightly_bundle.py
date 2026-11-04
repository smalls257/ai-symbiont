"""The trainer, merge and judge-server scripts that ship inside the installed package.

A `uv tool install` has no `scripts/routea`, so the scripts the nightly runs travel as package data
(`routea_bundle/*.script`; the suffix keeps them out of the import, type and network gates that read
`.py` files, because they import torch and serve on a socket on purpose). They import one another by
bare name, so they are copied to a folder as `.py` files before a Python runs them.
"""

import os
import shutil
from pathlib import Path

from symbiont.service.nightly_run import NightFailedError

ROUTEA_ENV = "SYMBIONT_ROUTEA_DIR"
TORCH_TRAINER = "train_lora_torch.py"
JUDGE_SERVER = "plug_judge_server.py"
# Where the package unpacks its scripts; HOME is read late, so an isolated user gets a copy.
UNPACKED = (".symbiont", "routea")
CHECKOUT_ROUTEA = Path(__file__).resolve().parents[3] / "scripts" / "routea"
BUNDLE = Path(__file__).resolve().parent / "routea_bundle"
SUFFIX = ".script"


class BundleMissingError(RuntimeError):
    """The package carries no scripts, so this install is damaged; reinstall it."""


def bundled_names() -> list[str]:
    """The module names the package carries. Raises BundleMissingError when it carries none."""
    names = sorted(path.name.removesuffix(SUFFIX) for path in BUNDLE.glob(f"*{SUFFIX}"))
    if not names:
        raise BundleMissingError(f"no scripts in {BUNDLE}; reinstall ai-symbiont")
    return names


def materialized(folder: Path) -> Path:
    """Copy the bundled scripts into `folder` as `.py` files (changed ones only); return it."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in bundled_names():
        source, target = BUNDLE / f"{name}{SUFFIX}", folder / f"{name}.py"
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            shutil.copyfile(source, target)
    return folder


def routea_dir() -> Path:
    """The scripts folder: $SYMBIONT_ROUTEA_DIR, a checkout's, else the unpacked package copy.

    Raises NightFailedError for a bad override, BundleMissingError for a package with no scripts.
    """
    chosen = os.environ.get(ROUTEA_ENV)
    if chosen:
        if not Path(chosen).is_dir():
            raise NightFailedError(f"{ROUTEA_ENV}={chosen} is not a folder")
        return Path(chosen)
    if CHECKOUT_ROUTEA.is_dir():
        return CHECKOUT_ROUTEA
    return materialized(Path.home().joinpath(*UNPACKED))


def torch_trainer() -> Path:
    """The torch trainer script. Raises NightFailedError when the scripts folder lacks it."""
    found = routea_dir() / TORCH_TRAINER
    if not found.is_file():
        raise NightFailedError(f"the CUDA trainer {TORCH_TRAINER} is not in {found.parent}")
    return found


def judge_script() -> str:
    """The judge server script: in the override, the checkout, or the unpacked package."""
    try:
        return str(routea_dir() / JUDGE_SERVER)
    except (NightFailedError, BundleMissingError, OSError) as missing:
        return f"<judge server script unavailable: {missing}>"
