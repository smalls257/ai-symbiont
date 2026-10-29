"""Training rows of the nightly update at 5, 10 and 25 lessons, for sizing a machine.

Usage: uv run python scripts/routea/nightly_scale.py --work W --lessons 5 10 25
W is a Plug a3 work dir (`plug_a3.py plan`): its per_repo, a3 and a3_replay rows are the pool.

The question is time and memory, not recall: how long does one night's update take for a repo with
N lessons beside habit replay? Rows are the real nightly mix (`plug_a3.arm_rows`, arm a3_replay)
over lessons pooled from several repos, so row lengths and counts match what a developer's repo
would produce. Output stays under W/scale/<N>/ and is never committed.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# training_messages yields 6 rows per lesson [measured: 30 per_repo rows for 5 lessons]
ROWS_PER_LESSON = 6
REPLAY_ARM = "a3_replay"


def habit_rows_from(replay: list[dict], plain: list[dict]) -> list[dict]:
    """The rows a replay mix holds beyond the plain mix, in replay order (multiset difference)."""
    left = Counter(json.dumps(r, sort_keys=True) for r in plain)
    extra = []
    for item in replay:
        key = json.dumps(item, sort_keys=True)
        if left[key] > 0:
            left[key] -= 1
        else:
            extra.append(item)
    return extra


def own_rows_for(lessons: int, pool: dict[str, list[dict]]) -> list[dict]:
    """A lesson count's own rows, repos taken in name order. Raises ValueError on a small pool."""
    needed = lessons * ROWS_PER_LESSON
    rows = [r for repo in sorted(pool) for r in pool[repo]]
    if len(rows) < needed:
        raise ValueError(f"{lessons} lessons needs {needed} rows, the pool has {len(rows)}")
    return rows[:needed]


def tiled(pool: list[dict], needed: int) -> list[dict]:
    """`pool` repeated up to `needed` rows (the habit pool is small). Raises ValueError if empty."""
    if not pool:
        raise ValueError("no habit rows to replay")
    return (pool * (needed // len(pool) + 1))[:needed] if needed > len(pool) else pool


def nightly_rows(own: list[dict], reading: list[dict], habits: list[dict]) -> list[dict]:
    """One night's rows: the new lessons, reading rows to keep the format, habit replay."""
    from plug_a3 import arm_rows  # noqa: PLC0415  (pulls the aidev lessons path)

    return arm_rows(own, reading, tiled(habits, len(own)), REPLAY_ARM)


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _pools(work: Path) -> tuple[dict, list, list]:
    """Per-repo own rows, reading rows and habit rows found under a Plug a3 work dir."""
    own, habits = {}, []
    for folder in sorted((work / "repos").iterdir()):
        own[folder.name] = _read(folder / "per_repo" / "train.jsonl")
        replay = _read(folder / REPLAY_ARM / "train.jsonl")
        habits += habit_rows_from(replay, _read(folder / "a3" / "train.jsonl"))
    reading = [
        r
        for r in _read(work / "meta" / "train.jsonl")
        if "What you remember:" in r["messages"][0]["content"]
    ]
    unique = list({json.dumps(h, sort_keys=True): h for h in habits}.values())
    return own, reading, unique


def write_scales(work: Path, counts: list[int]) -> dict[int, int]:
    """Write scale/<N>/train.jsonl for each count; return the row count per lesson count."""
    own, reading, habits = _pools(work)
    written = {}
    for lessons in counts:
        rows = nightly_rows(own_rows_for(lessons, own), reading, habits)
        folder = work / "scale" / str(lessons)
        folder.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(r) + "\n" for r in rows)
        (folder / "train.jsonl").write_text(text)
        (folder / "valid.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows[:8]))
        written[lessons] = len(rows)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--lessons", type=int, nargs="+", required=True)
    args = parser.parse_args()
    print(json.dumps(write_scales(args.work, args.lessons)))


if __name__ == "__main__":
    main()
