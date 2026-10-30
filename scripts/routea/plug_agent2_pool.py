"""PLUG-AGENT-2 pool: later tasks, their SWE-rebench rows and their same-repo lesson stores.

Runs on the desktop (duckdb and the exports are there). A task is a candidate when its repository
has an earlier dated task, its row has a docker image and at least one lesson mined from an
earlier instance of the same repository exists. Rows stay local; the summary holds ids and counts.
Usage: python plug_agent2_pool.py <pool.json> <sessions-dir> <out-dir>
"""

import json
import pickle
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import build_lessons
import duckdb
from lessons import Lesson, lessons_in_session
from plug import distinct

SOURCE = "hf://datasets/nebius/SWE-rebench@~parquet/default/test/*.parquet"
COLUMNS = (
    "instance_id, repo, base_commit, created_at, patch, test_patch, problem_statement, "
    "install_config, FAIL_TO_PASS, PASS_TO_PASS, docker_image"
)
STORE_SIZE = 40  # most recent lessons of the repository; a longer list would dilute Spark's labels
FETCH_TRIES = 6


def local_shards(cache: Path) -> list[str]:
    """The SWE-rebench test split's parquet files, downloaded once with backoff on rate limits."""
    from huggingface_hub import HfApi, hf_hub_download  # noqa: PLC0415  only this stage needs it

    revision = "refs/convert/parquet"
    listing = HfApi().list_repo_files("nebius/SWE-rebench", repo_type="dataset", revision=revision)
    names = [
        x
        for x in listing
        if x.startswith(("default/test/", "default/filtered/")) and x.endswith(".parquet")
    ]
    paths = []
    for name in names:
        for attempt in range(FETCH_TRIES):
            try:
                paths.append(
                    hf_hub_download(
                        "nebius/SWE-rebench",
                        name,
                        repo_type="dataset",
                        revision=revision,
                        local_dir=cache,
                    )
                )
                break
            except OSError as error:
                print(f"download {name} attempt {attempt + 1}: {str(error)[:80]}", flush=True)
                time.sleep(30 * (attempt + 1))
        else:
            raise RuntimeError(f"{name} could not be downloaded; nothing was guessed")
    return paths


def fetch_rows(ids: list[str], cache: Path) -> list[dict]:
    """SWE-rebench rows of `ids` from the local parquet shards."""
    con = duckdb.connect()
    marks = ", ".join("?" for _ in ids)
    files = ", ".join(f"'{path}'" for path in local_shards(cache))
    query = f"SELECT {COLUMNS} FROM read_parquet([{files}]) WHERE instance_id IN ({marks})"  # noqa: S608
    cursor = con.execute(query, ids)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]


def lessons_by_instance(sessions: Path) -> dict[str, list[Lesson]]:
    """Every readable session's lessons keyed by its task id, from all export directories."""
    found: dict[str, list[Lesson]] = {}
    for directory in sorted(sessions.glob("*/pool")):
        for session in build_lessons._sessions(directory, []):
            found.setdefault(session[0].task_id, []).extend(lessons_in_session(session, Counter()))
    return {
        task: [x for lst in distinct(lessons).values() for x in lst]
        for task, lessons in found.items()
    }


def store_of(
    task: str, repo_tasks: list[str], dates: dict[str, str], by_instance: dict[str, list[Lesson]]
) -> list[Lesson]:
    """Same-repo lessons of instances created strictly before `task`, the most recent STORE_SIZE."""
    earlier = [name for name in repo_tasks if dates[name] < dates[task]]
    earlier.sort(key=lambda name: (dates[name], name), reverse=True)
    lessons = [lesson for name in earlier for lesson in by_instance.get(name, [])]
    distinct_failures = {(lesson.failed, lesson.error): lesson for lesson in reversed(lessons)}
    return list(distinct_failures.values())[::-1][:STORE_SIZE]


def main() -> None:
    pool = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "lessons.pickle"
    if not cache.is_file():
        cache.write_bytes(pickle.dumps(lessons_by_instance(Path(sys.argv[2]))))
    by_instance = pickle.loads(cache.read_bytes())  # noqa: S301 written by this script a step earlier
    wanted = {name: (repo, v["dates"]) for repo, v in pool.items() for name in v["tasks"][1:]}
    rows = {row["instance_id"]: row for row in fetch_rows(sorted(wanted), out / "parquet")}
    stores, drops = {}, Counter()
    for task, (repo, dates) in sorted(wanted.items()):
        row = rows.get(task)
        if row is None:
            drops["not in SWE-rebench test split"] += 1
        elif not row["docker_image"]:
            drops["no docker image"] += 1
        elif not (store := store_of(task, pool[repo]["tasks"], dates, by_instance)):
            drops["no earlier lesson"] += 1
        else:
            stores[task] = {
                "repo": repo,
                "created_at": dates[task],
                "lessons": [asdict(x) for x in store],
            }
    (out / "stores.json").write_text(json.dumps(stores))
    (out / "rows.json").write_text(json.dumps([rows[name] for name in stores], default=str))
    summary = {
        "repos": len(pool),
        "later_tasks": len(wanted),
        "candidates": len(stores),
        "dropped": dict(drops),
    }
    (out / "pool-summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
