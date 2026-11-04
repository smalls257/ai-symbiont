"""Find the Llama base and the nightly kit files a first `symbiont nightly` needs.

The search is a pure function over candidate roots; the environment is read once, in
`search_roots`. Nothing found raises `ModelsNotFoundError` with the download commands. The
"saved path" is the built judge kit: once merged, nothing else is needed (`resolved_downloads`).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from symbiont.service.nightly_background import KitFiles, kit_problem
from symbiont.service.nightly_kit import BASE_MARKER, OWN_BASE, OWN_KIT
from symbiont.service.nightly_setup import (
    BASE_MODEL,
    KIT_FOLDER,
    KIT_PINS,
    KIT_PLAIN_FILES,
    KIT_REPO,
    KitSetupError,
)

MODELS_FOLDER = "models"
HF_BASE_CACHE = "models--" + BASE_MODEL.replace("/", "--")
HF_KIT_CACHE = "models--" + KIT_REPO.replace("/", "--")


class ModelsNotFoundError(KitSetupError):
    """No usable base or kit was found on this machine; the message says how to get them."""


@dataclass(frozen=True)
class SearchRoots:
    """Where the model folders may be: symbiont's own folder and the Hugging Face hub cache."""

    models: Path
    hf_hub: Path


def search_roots(environ: Mapping[str, str], data_dir: Path, home: Path) -> SearchRoots:
    """The roots for this machine: `<data dir>/models`, and the hub cache.

    `HF_HOME/hub` wins over `~/.cache/huggingface/hub`.
    """
    hf_home = environ.get("HF_HOME")
    hub = Path(hf_home) / "hub" if hf_home else home / ".cache" / "huggingface" / "hub"
    return SearchRoots(data_dir / MODELS_FOLDER, hub)


def is_base_folder(folder: Path) -> bool:
    """A model folder has config and weights; `check_base` later verifies the model itself."""
    return (folder / BASE_MARKER).is_file() and any(folder.glob("*.safetensors"))


def is_kit_folder(folder: Path) -> bool:
    """Every file `check_kit_files` will hash is present; its pins decide if they are right."""
    return all((folder / name).is_file() for name in (*KIT_PINS, *KIT_PLAIN_FILES))


def locate_base(roots: SearchRoots) -> Path | None:
    """The first usable Llama base: symbiont's own folder, else the newest hub snapshot."""
    own = roots.models / OWN_BASE
    if is_base_folder(own):
        return own
    return _first_valid(_snapshots(roots.hf_hub / HF_BASE_CACHE), is_base_folder)


def locate_kit_files(roots: SearchRoots) -> Path | None:
    """The first usable `nightly-kit` folder: symbiont's own, else in the newest hub snapshot."""
    own = roots.models / OWN_KIT
    if is_kit_folder(own):
        return own
    inside = [snap / KIT_FOLDER for snap in _snapshots(roots.hf_hub / HF_KIT_CACHE)]
    return _first_valid(inside, is_kit_folder)


def _snapshots(repo_cache: Path) -> list[Path]:
    """Snapshot folders of one hub repo, newest first (ties broken by name, descending)."""
    folder = repo_cache / "snapshots"
    if not folder.is_dir():
        return []
    found = [path for path in folder.iterdir() if path.is_dir()]
    return sorted(found, key=lambda path: (path.stat().st_mtime, path.name), reverse=True)


def _first_valid(candidates: list[Path], is_valid: Callable[[Path], bool]) -> Path | None:
    return next((path for path in candidates if is_valid(path)), None)


def missing_models_message(roots: SearchRoots, lacking: list[str]) -> str:
    """What was not found, where it looked, and how to get it (by symbiont, or by hand)."""
    return (
        f"no {' and no '.join(lacking)} found on this machine "
        f"(looked in {roots.models} and {roots.hf_hub}). `symbiont nightly start` (or "
        f"/symbiont onboard) downloads them for you (about 2.5 GB and 100 MB). By hand instead: "
        f"1. accept Meta's license at https://huggingface.co/{BASE_MODEL} and run "
        f"`hf auth login`; "
        f"2. `hf download {BASE_MODEL}`; "
        f'3. `hf download {KIT_REPO} --include "{KIT_FOLDER}/*"`; '
        "then run /symbiont onboard again"
    )


def resolved_downloads(given: KitFiles, kit_dir: Path, roots: SearchRoots) -> KitFiles:
    """The base and kit folders to merge: those given win, then the search; a built kit needs none.

    Raises ModelsNotFoundError with the download commands when a needed folder is not found.
    """
    if given.base is not None and given.kit_files is not None:
        return given
    if kit_problem(kit_dir) is None:
        return given
    base = given.base or locate_base(roots)
    kit_files = given.kit_files or locate_kit_files(roots)
    lacking = [
        what
        for what, found in (
            ("Llama 3.2 1B Instruct model", base),
            ("symbiont nightly kit", kit_files),
        )
        if found is None
    ]
    if lacking:
        raise ModelsNotFoundError(missing_models_message(roots, lacking))
    return KitFiles(base, kit_files)
