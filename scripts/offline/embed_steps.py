"""Embed the text of every pool step once, for the T49 text ceiling probe (cache under data/).

One float32 matrix per pool repository, rows in the replay order of `run_repo_curve.load_repo`
(sessions in the seeded order, steps in order), so row i is the step whose 86 features are row i
of the warmed columns; `run_text_ceiling` refuses a matrix whose row count differs. The text of a
step is `step_text.step_text`: it is embedded locally on the CPU and never printed or logged,
only counts. The model is a small public sentence embedder fetched once into the cache dir.

    embed_steps.py --pool results/repo-pool.json --data-dir data/nebius-openhands/pool \
        --out-dir data/text-ceiling/embeddings --model-dir data/text-ceiling/model --workers 10
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import run_repo_curve as rc
import run_selection as g6
from step_text import step_text

log = logging.getLogger("embed-steps")
MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # 384 dims, 6 layers: cheap on a CPU
DIMS = 384
BATCH = 64
SETTINGS: dict[str, Path] = {}
_EMBEDDER: list[Any] = []  # one per forked worker, made on its first job


def _embedder(threads: int) -> Any:
    """The embedder, imported here: importing onnxruntime in a parent that later forks numpy
    workers (run_text_ceiling) crashed them in Accelerate's thread pool (SIGSEGV, T49)."""
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL, cache_dir=str(SETTINGS["model_dir"]), threads=threads)


def embedding_path(out_dir: Path, repo: str) -> Path:
    """Where one repository's matrix is cached."""
    return out_dir / (repo.replace("/", "__") + ".npy")


def embed_repo(repo: str) -> tuple[str, int, float]:
    """Embed one repository's steps unless its matrix is already cached; (repo, rows, seconds)."""
    started, target = time.time(), embedding_path(SETTINGS["out_dir"], repo)
    if target.exists():
        return repo, int(np.load(target, mmap_mode="r").shape[0]), 0.0
    sessions = rc.load_repo(SETTINGS["data_dir"] / (repo.replace("/", "__") + ".jsonl"), repo)
    texts = [step_text(record) for session in sessions for record in session]
    if not _EMBEDDER:
        _EMBEDDER.append(_embedder(1))
    matrix = np.asarray(list(_EMBEDDER[0].embed(texts, batch_size=BATCH)), dtype=np.float32)
    if matrix.shape != (len(texts), DIMS):
        raise ValueError(f"{repo}: embedder returned {matrix.shape} for {len(texts)} steps")
    partial = target.with_suffix(".partial.npy")
    np.save(partial, matrix)
    partial.rename(target)
    seconds = time.time() - started
    log.info("%s: %d steps embedded (%.0fs)", repo, len(texts), seconds)
    return repo, len(texts), seconds


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Embed every pool repository; write a manifest of counts beside the matrices."""
    started = time.time()
    SETTINGS.update(
        data_dir=Path(args.data_dir), out_dir=Path(args.out_dir), model_dir=Path(args.model_dir)
    )
    SETTINGS["out_dir"].mkdir(parents=True, exist_ok=True)
    _embedder(1)  # fetch the weights once, not per worker
    repos = [entry["repo"] for entry in json.loads(Path(args.pool).read_text())["repos"]]
    done = g6.pool_map(embed_repo, repos, args.workers)
    manifest = {
        "model": MODEL,
        "dims": DIMS,
        "repos": len(done),
        "steps": sum(rows for _, rows, _ in done),
        "rows_by_repo": {repo: rows for repo, rows, _ in done},
        "wall_clock_s": time.time() - started,
    }
    (SETTINGS["out_dir"] / "manifest.json").write_text(json.dumps(manifest, indent=1))
    log.info(
        "embedded %d steps of %d repositories (%.0fs)",
        manifest["steps"],
        len(done),
        manifest["wall_clock_s"],
    )
    return manifest


def main() -> None:
    """Parse the command line and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    for name in ("pool", "data-dir", "out-dir", "model-dir"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--workers", type=int, default=10)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
