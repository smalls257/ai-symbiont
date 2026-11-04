"""Download the Llama base and the nightly kit into `<data dir>/models` through `egress`.

The base is `unsloth/Llama-3.2-1B-Instruct`, a public copy of Meta's weights (the meta-llama repo
is gated and needs a login the MCP tool cannot do); `check_base` still verifies the model. The
job file carries bytes done and total so a 2.5 GB download is not mistaken for a hang.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symbiont.egress import DownloadError, download_file, file_url, get_json, listing_url
from symbiont.service.nightly_job import JobPhase, JobState, utc_now, write_job
from symbiont.service.nightly_kit import OWN_BASE, OWN_KIT
from symbiont.service.nightly_run import NightPlan, Say
from symbiont.service.nightly_setup import KIT_FOLDER, KIT_REPO

BASE_REPO = "unsloth/Llama-3.2-1B-Instruct"
BASE_FILES = frozenset(
    {
        "config.json",
        "generation_config.json",
        "model.safetensors",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "chat_template.jinja",
    }
)
# Write the job file about every 32 MB, not every chunk: status is read by people, not loops.
PROGRESS_STEP = 32 << 20

Lister = Callable[[str], Any]
Fetch = Callable[[str, Path, int, Callable[[int, int | None], None]], int]


@dataclass(frozen=True)
class ModelFile:
    """One file to bring in: where from, where to, and how many bytes it must have."""

    url: str
    target: Path
    size: int


def files_to_fetch(
    listing: Sequence[dict[str, Any]],
    repo: str,
    prefix: str,
    wanted: frozenset[str] | None,
    into: Path,
) -> list[ModelFile]:
    """The files of an API listing under `prefix` (all, or only `wanted` names), with targets."""
    found = []
    for entry in listing:
        path = str(entry.get("path", ""))
        if entry.get("type") != "file" or not path.startswith(prefix):
            continue
        name = path.removeprefix(prefix)
        if wanted is not None and name not in wanted:
            continue
        found.append(ModelFile(file_url(repo, path), into / name, int(entry["size"])))
    return found


def still_missing(files: Sequence[ModelFile]) -> list[ModelFile]:
    """Files that are absent or have the wrong size (a present, right-sized file is skipped)."""
    return [f for f in files if not f.target.is_file() or f.target.stat().st_size != f.size]


def plan_downloads(models_dir: Path, lister: Lister = get_json) -> list[ModelFile]:
    """Every file of the base and the kit, listed from Hugging Face (two small API calls)."""
    base = files_to_fetch(
        lister(listing_url(BASE_REPO)), BASE_REPO, "", BASE_FILES, models_dir / OWN_BASE
    )
    kit_prefix = KIT_FOLDER + "/"
    kit_listing = lister(listing_url(KIT_REPO, KIT_FOLDER))
    kit = files_to_fetch(kit_listing, KIT_REPO, kit_prefix, None, models_dir / OWN_KIT)
    missing_names = BASE_FILES - {f.target.name for f in base}
    if missing_names:
        raise DownloadError(f"{BASE_REPO} no longer lists {sorted(missing_names)}")
    if not kit:
        raise DownloadError(f"{KIT_REPO} lists no files under {KIT_FOLDER}/")
    return [*base, *kit]


def download_models(
    models_dir: Path,
    report: Callable[[int, int], None],
    lister: Lister = get_json,
    fetch: Fetch = download_file,
) -> int:
    """Fetch what is missing; `report(done, total)` runs as bytes arrive. Returns files fetched.

    Raises DownloadError or EgressRefusedError naming the URL's host and path; no partial file
    keeps its final name.
    """
    todo = still_missing(plan_downloads(models_dir, lister))
    total = sum(f.size for f in todo)
    finished = 0
    for file in todo:
        base = finished

        def progress(done: int, _expected: int | None, base: int = base) -> None:
            report(base + done, total)

        report(finished, total)
        fetch(file.url, file.target, file.size, progress)
        finished += file.size
    report(finished, total)
    return len(todo)


class JobProgress:
    """Writes the downloading state to the job file about every `PROGRESS_STEP` bytes."""

    def __init__(self, plan: NightPlan, started: str, lessons: int | None) -> None:
        """Remember whose job file to write and what to keep in it."""
        self._plan, self._started, self._lessons = plan, started, lessons
        self._last_step = -1

    def __call__(self, done: int, total: int) -> None:
        """Write when a new step was crossed (and at 0 and at the end)."""
        step = done // PROGRESS_STEP
        if step == self._last_step and done != total:
            return
        self._last_step = step
        state = JobState(JobPhase.DOWNLOADING, self._started, self._lessons, None, "", done, total)
        write_job(self._plan.nightly_dir, self._plan.project, state)


def fetch_for_job(
    plan: NightPlan, models_dir: Path, started: str, lessons: int | None, say: Say
) -> None:
    """The job's first phase: download, leaving the job file `running` again when done."""
    say(f"downloading the model and kit into {models_dir} (about 2.5 GB; public files, no login)")
    count = download_models(models_dir, JobProgress(plan, started, lessons))
    say(f"downloaded {count} files into {models_dir}")
    write_job(
        plan.nightly_dir, plan.project, JobState(JobPhase.RUNNING, started or utc_now(), lessons)
    )
