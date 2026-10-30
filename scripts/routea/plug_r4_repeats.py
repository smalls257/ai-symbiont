"""Plug round 4, plentiful real repeats: the same normalized error again, counted in code only.

Usage: uv run python scripts/routea/plug_r4_repeats.py count --pool P... --normalizer N \
Usage:   --exclude X... --out F

Within a session, or across sessions of one task, the same error line (masked by the downstream
agent's normalizer, loaded from its checkout so both tests agree) counts as a repeat; "fixed"
means a later command of the same program succeeded. Counts only; no text leaves this process.
"""

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from lessons import error_line  # noqa: E402
from plug_r4_recur import repo_of  # noqa: E402

from symbiont.miner.commands import normalise_command  # noqa: E402
from symbiont.records.schema import Kind  # noqa: E402


def load_normalizer(path: Path):
    """The downstream normalizer module, loaded from its file; its sha256 is returned too."""
    spec = importlib.util.spec_from_file_location("plug_agent2_errorline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, hashlib.sha256(path.read_bytes()).hexdigest()


def session_failures(session, normalizer) -> list[tuple[int, str, str]]:
    """(position, normalized error, program) of each failed command naming an error."""
    found = []
    for position, record in enumerate(session):
        if record.kind == Kind.COMMAND and record.exit_code and record.command:
            line = error_line(record.raw)
            key = normalizer.normalize_error_line(line) if line else ""
            if key:
                found.append((position, key, normalise_command(record.command)[0]))
    return found


def fixed_later(session, position: int, program: str) -> bool:
    """A later command of the same program succeeded after the failure at `position`."""
    return any(
        r.kind == Kind.COMMAND
        and r.exit_code == 0
        and r.command
        and normalise_command(r.command)[0] == program
        for r in session[position + 1 :]
    )


def within_session(session, failures) -> list[tuple[str, bool]]:
    """Per repeated key: (key, fixed) where the key's first failure was later fixed."""
    first, seen = {}, defaultdict(int)
    for position, key, program in failures:
        first.setdefault(key, (position, program))
        seen[key] += 1
    return [(k, fixed_later(session, *first[k])) for k, n in seen.items() if n >= 2]


def add_cross_counts(by_task: dict, normalizer, rows: dict) -> None:
    """Count each (task, key) seen in two or more sessions of the task, generic apart."""
    for (repo, _), keys in by_task.items():
        for key, sessions in keys.items():
            if len(sessions) >= 2:
                kind = "generic" if normalizer.is_generic_environment(key) else "code"
                rows[repo][f"cross_{kind}"] += 1


def count_pools(pools: list[Path], normalizer, excluded: set[str]) -> dict:
    """Per repository: within-session and cross-session repeat counts, generic ones apart."""
    import build_lessons  # noqa: PLC0415  (reads the exports)

    seen: set[str] = set()
    rows = defaultdict(lambda: defaultdict(int))
    by_task: dict[tuple[str, str], dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for pool in pools:
        for session in build_lessons._sessions(pool, []):
            repo, sid = repo_of(session), session[0].session_id
            if repo in excluded or sid in seen:
                continue
            seen.add(sid)
            failures = session_failures(session, normalizer)
            for key, fixed in within_session(session, failures):
                kind = "generic" if normalizer.is_generic_environment(key) else "code"
                rows[repo][f"within_{kind}"] += 1
                rows[repo][f"within_{kind}_fixed"] += fixed
            for _, key, _ in failures:
                by_task[(repo, session[0].task_id)][key].add(sid)
    add_cross_counts(by_task, normalizer, rows)
    return {repo: dict(v) for repo, v in rows.items()}


def totals(per_repo: dict) -> dict:
    """Source totals and repositories with at least one repeat of each kind."""
    kinds = sorted({k for v in per_repo.values() for k in v})
    return {
        k: {
            "repeats": sum(v.get(k, 0) for v in per_repo.values()),
            "repos": sum(1 for v in per_repo.values() if v.get(k)),
        }
        for k in kinds
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("count",))
    parser.add_argument("--pool", type=Path, nargs="+", required=True)
    parser.add_argument("--normalizer", type=Path, required=True)
    parser.add_argument("--exclude", type=Path, nargs="*", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    excluded: set[str] = set()
    for path in args.exclude:
        excluded |= set(json.loads(path.read_text()))
    normalizer, digest = load_normalizer(args.normalizer)
    per_repo = count_pools(args.pool, normalizer, excluded)
    document = {
        "normalizer_sha256": digest,
        "excluded_repos": len(excluded),
        "totals": totals(per_repo),
        "per_repo": per_repo,
    }
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    print(
        json.dumps(
            {"normalizer_sha256": digest[:12], "repos": len(per_repo), "totals": document["totals"]}
        )
    )


if __name__ == "__main__":
    main()
