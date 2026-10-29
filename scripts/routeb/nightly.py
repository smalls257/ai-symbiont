"""Route B overnight, per repo: mine, export, rows, upload, train, install, verify, forget.

Each repo's personal Glimmer (Muse-Glimmer-30B-<repo>) learns the day's new lessons through
ops/gpu_run.sh on the training host, plain Glimmer keeps no adapter, and lessons are forgotten
only after verify passes. Glimmer is never left down: a failed step ends with it up on the last
good preset. A script, not a `symbiont` subcommand: src/ may not launch ssh (scripts/AGENTS.md).

Usage: uv run python scripts/routeb/nightly.py [--config FILE] [--repo NAME] [--dry-run]
"""

import argparse
import glob
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from nightly_config import ConfigError, NightlyConfig, RepoConfig, config_path, load_config
from nightly_host import DryRunHost, HostStepError, TrainingHost

from symbiont.miner.lessons import Lesson
from symbiont.miner.trained import lesson_id
from symbiont.readers import READERS
from symbiont.routeb.lesson_rows import memory_system, training_rows, verify_questions
from symbiont.store.local import ForgetMismatchError, Source, Store
from symbiont.store.mining import MiningRules, remine
from symbiont.store.training import lessons_for_personal_model

STEPS = ("mine", "export", "rows", "upload", "train", "install", "verify", "forget")
# 0: every repo learned or had nothing new. 1: a repo failed and Glimmer is back up on its last
# good preset. 2: bad config. 70: Glimmer could not be brought back (the host's exit 70).
EXIT_FAILED, EXIT_CONFIG, EXIT_GLIMMER_DOWN = 1, 2, 70


class NightStepError(RuntimeError):
    """A local step failed; the message names the step and the cause."""


@dataclass
class Night:
    """One repo's night: where things live locally and on the host, and what was done so far."""

    config: NightlyConfig
    repo: RepoConfig
    host: TrainingHost
    store: Store
    stamp: str
    dry_run: bool
    lessons: list[Lesson] = field(default_factory=list)
    uploaded: bool = False

    @property
    def model(self) -> str:
        """The repo's personal Glimmer name on the router."""
        return f"{self.config.host.model_prefix}-{self.repo.name}"

    @property
    def adapter_set(self) -> str:
        """Tonight's adapter name: new every night, so the last good GGUF is never overwritten."""
        return f"{self.repo.name}-{self.stamp}"

    @property
    def host_work(self) -> str:
        """Tonight's work directory on the host."""
        return f"{self.config.host.work_root}/{self.repo.name}/{self.stamp}"

    @property
    def local_work(self) -> Path:
        """Tonight's rows before upload; deleted when the night ends."""
        return self.config.data_dir / "nightly" / "work" / self.adapter_set

    @property
    def state_file(self) -> Path:
        """The repo's last good adapter, so tomorrow continues from it."""
        return self.config.data_dir / "nightly" / f"{self.repo.name}.json"

    def say(self, line: str) -> None:
        """One progress line on stdout; counts and names only, never lesson text."""
        print(f"nightly {self.repo.name}: {line}", flush=True)

    def begin(self, step: str, detail: str) -> None:
        """Announce step `step` of eight."""
        self.say(f"[{STEPS.index(step) + 1}/{len(STEPS)}] {step}: {detail}")


def mine(night: Night) -> None:
    """Re-read every registered log plus the configured ones; the store keeps lessons only."""
    sources = [source for spec in night.repo.sources for source in _sources(night.repo, spec)]
    known = night.store.sources(night.repo.project)
    night.begin("mine", f"{len(known)} registered logs, {len(sources)} configured")
    if night.dry_run:
        night.say("  dry run: the stored lessons stand in for tonight's mining")
        return
    rules = MiningRules(READERS, night.repo.held_out)
    try:
        lessons = remine(night.store, night.repo.project, rules, adding=sources)
    except (OSError, ValueError) as failed:  # unreadable log, unknown reader, held-out task
        raise NightStepError(f"mine: {failed}") from failed
    night.say(f"  {len(lessons)} lessons from {len(night.store.sources(night.repo.project))} logs")


def _sources(repo: RepoConfig, spec: str) -> list[Source]:
    """READER=PATH, where PATH may be a glob so each day's new session files are picked up.

    A glob that matches nothing raises: a mistyped path must not look like a quiet day.
    """
    reader, _, pattern = spec.partition("=")
    if not pattern:
        raise NightStepError(f"mine: a source must be READER=PATH, got {spec!r}")
    expanded = Path(pattern).expanduser()
    if not glob.has_magic(str(expanded)):
        return [Source(repo.project, reader, str(expanded))]
    paths = sorted(glob.glob(str(expanded)))
    if not paths:
        raise NightStepError(f"mine: {spec!r} matches no file")
    return [Source(repo.project, reader, path) for path in paths]


def export(night: Night) -> None:
    """The repo's lessons no personal model has learned yet (re-mining brings trained ones back)."""
    trained = night.store.trained_lesson_ids(night.repo.project)
    every = lessons_for_personal_model(night.store, night.repo.project)
    night.lessons = [lesson for lesson in every if lesson_id(lesson) not in trained]
    night.begin("export", f"{len(night.lessons)} new of {len(every)} stored lessons")


def build_rows(night: Night) -> None:
    """Write the training rows, the held-out questions and the system turn, locally."""
    rows = training_rows(night.repo.name, night.lessons)
    questions = verify_questions(night.repo.name, night.lessons)
    kinds = {kind: sum(row.kind == kind for row in rows) for kind in ("self-study", "action")}
    night.begin(
        "rows",
        f"{len(rows)} rows ({kinds['self-study']} self-study, {kinds['action']} action), "
        f"{len(questions)} verify questions",
    )
    if night.dry_run:
        return
    train_dir = night.local_work / "train" / night.adapter_set
    train_dir.mkdir(parents=True, mode=0o700)
    _write_lines(train_dir / "train.jsonl", [{"messages": row.messages} for row in rows])
    _write_lines(night.local_work / "questions.jsonl", [q.__dict__ for q in questions])
    (night.local_work / "system.txt").write_text(memory_system(night.repo.name), encoding="utf-8")


def _write_lines(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    path.chmod(0o600)


def upload(night: Night) -> None:
    """Copy tonight's work directory to the host."""
    night.begin("upload", f"rows to {night.config.host.ssh}:{night.host_work}")
    names = ("train", "questions.jsonl", "system.txt")
    night.uploaded = True  # set first: a half-finished copy is still cleaned up
    night.host.upload([night.local_work / name for name in names], night.host_work)


def train(night: Night) -> None:
    """Train through ops/gpu_run.sh on the host, continuing from the last good adapter."""
    start_from = _last_good(night).get("adapter_dir", "")
    begun = f"continuing from {start_from}" if start_from else "first adapter for this repo"
    night.begin("train", f"{night.adapter_set}, {begun}")
    args = [night.host_work, night.adapter_set] + ([start_from] if start_from else [])
    night.host.step("train", *args)


def install(night: Night) -> None:
    """Add or replace the personal name in the router preset and restart Glimmer."""
    night.begin("install", f"{night.model} = plain Glimmer + glimmer-{night.adapter_set}.gguf")
    night.host.step("install", night.model, night.adapter_set)


def verify(night: Night) -> None:
    """Plain answers plain, the personal name answers with a lesson card."""
    night.begin("verify", f"plain has no adapter; {night.model} answers with a lesson card")
    night.host.step("verify", night.host_work, night.model, night.adapter_set)


def forget(night: Night) -> None:
    """Delete the trained lessons, keeping a manifest of ids and counts; remember the adapter."""
    manifest = night.config.data_dir / "manifests" / f"routeb-{night.adapter_set}.json"
    night.begin("forget", f"{len(night.lessons)} lessons; manifest {manifest}")
    if night.dry_run:
        return
    try:
        forgotten = night.store.forget_trained(night.repo.project, manifest, exported=night.lessons)
    except (OSError, ForgetMismatchError) as failed:
        raise NightStepError(f"forget: {failed}; {night.model} stays installed") from failed
    adapter_dir = f"{night.host_work}/adapters/{night.adapter_set}"
    state = {"stamp": night.stamp, "model": night.model, "adapter_dir": adapter_dir}
    night.state_file.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    night.say(f"  forgot {forgotten} lessons; {night.model} now holds them")


def _last_good(night: Night) -> dict[str, str]:
    if not night.state_file.exists():
        return {}
    return json.loads(night.state_file.read_text(encoding="utf-8"))


def learn_overnight(night: Night) -> int:
    """All eight steps for one repo; returns its exit code. Glimmer is up whatever happens."""
    try:
        for step in (mine, export):
            step(night)
        if not night.lessons:
            night.say("nothing new to learn; Glimmer untouched")
            return 0
        build_rows(night)
        upload(night)
        _on_host(night)
        forget(night)
    except NightStepError as failed:
        night.say(f"FAILED {failed}")
        return EXIT_FAILED
    except HostStepError as failed:
        night.say(f"FAILED {failed}")
        return EXIT_GLIMMER_DOWN if failed.glimmer_down else EXIT_FAILED
    finally:
        _clean(night)
    if night.dry_run:
        night.say(f"dry run done: {night.model} would learn {len(night.lessons)} lessons")
    else:
        night.say(f"done: {night.model} learned {len(night.lessons)} lessons")
    return 0


def _on_host(night: Night) -> None:
    """Train, install, verify; brings Glimmer back on the right preset if any of them fails."""
    try:
        train(night)
        install(night)
    except HostStepError as failed:
        night.say(f"  {failed.step} failed; making sure Glimmer is up on the preset it had")
        _recover(night, "ensure-up", failed)
    try:
        verify(night)
    except HostStepError as failed:
        night.say("  verify failed; restoring the last good preset")
        _recover(night, "restore", failed)


def _recover(night: Night, step: str, failed: HostStepError) -> None:
    """Run the recovery host step, then re-raise the original failure (or the recovery's)."""
    if not failed.glimmer_down:
        night.host.step(step)
    raise failed


def _clean(night: Night) -> None:
    """Rows hold lesson text: remove them locally and on the host however the night ended."""
    if night.local_work.exists():
        shutil.rmtree(night.local_work)
    if night.uploaded:
        try:
            night.host.step("clean", night.host_work)
        except HostStepError as failed:
            night.say(f"WARNING rows left on the host in {night.host_work}: {failed}")


def main(argv: list[str] | None = None) -> int:
    """Run every configured repo (or one); the worst exit code wins."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--config",
        type=Path,
        help="default: $SYMBIONT_NIGHTLY_CONFIG or ~/.config/symbiont/nightly.toml",
    )
    parser.add_argument("--repo", help="only this [[repo]] name")
    parser.add_argument("--dry-run", action="store_true", help="print every step, run nothing")
    args = parser.parse_args(argv)
    try:
        config = load_config(config_path(args.config))
        repos = _chosen(config, args.repo)
    except ConfigError as bad:
        print(f"nightly: {bad}", file=sys.stderr)
        return EXIT_CONFIG
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    config.data_dir.mkdir(parents=True, exist_ok=True)
    (config.data_dir / "nightly").mkdir(exist_ok=True)
    store = Store.open(config.data_dir / "store.db")
    codes = [
        learn_overnight(_night(config, repo, store, stamp, dry_run=args.dry_run)) for repo in repos
    ]
    return max(codes, default=0)


def _chosen(config: NightlyConfig, name: str | None) -> tuple[RepoConfig, ...]:
    if name is None:
        return config.repos
    chosen = tuple(repo for repo in config.repos if repo.name == name)
    if not chosen:
        raise ConfigError(
            f"no [[repo]] named {name!r}; configured: {[r.name for r in config.repos]}"
        )
    return chosen


def _night(
    config: NightlyConfig, repo: RepoConfig, store: Store, stamp: str, *, dry_run: bool
) -> Night:
    host = DryRunHost(config.host, print) if dry_run else TrainingHost(config.host)
    return Night(config, repo, host, store, stamp, dry_run)


if __name__ == "__main__":
    sys.exit(main())
