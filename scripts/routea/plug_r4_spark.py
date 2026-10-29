"""Plug round 4's Spark calls: rewrite each lesson as a trigger sentence, or invent situations.

Usage: uv run python scripts/routea/plug_r4_spark.py rewrite --pool P [--repos R.json] --out O
Usage: uv run python scripts/routea/plug_r4_spark.py invent --pool P --repos R.json --count 30
Usage:   --out O

Spark sees only each lesson's template text (`Lesson.text()`, from the public nebius pool), through
`symbiont.egress.spark` on the Contributor tier with the ledger and a run cap. Results append to
JSONL as they come (a rerun skips done lessons); a rejected reply is recorded with its reason and
counted, never replaced by the template silently. Prints counts and spend, never text.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

import build_lessons  # noqa: E402
from lessons import Lesson  # noqa: E402
from plug import distinct  # noqa: E402
from plug_r4_text import (  # noqa: E402
    RewriteRejectedError,
    SituationsRejectedError,
    checked_rewrite,
    invent_prompt,
    parsed_situations,
    rewrite_prompt,
)

from symbiont.egress.credentials import load_meta_key  # noqa: E402
from symbiont.egress.spark import Effort, SparkApiError, SparkReply, SparkSession  # noqa: E402
from symbiont.egress.spend import Ledger, Tier, caps_from_environment  # noqa: E402
from symbiont.readers.openhands import PROVENANCE  # noqa: E402

MODEL = "muse-spark-1.3-contributor"  # the owner's approved Contributor model
RUN = "plug-r4-spark"
WORKERS = 3  # 6 hit the Contributor tier's rate limit (429) on the first full run
RATE_LIMIT_TRIES = 6
RATE_LIMIT_WAIT_S = 20.0  # doubled after each 429
RETRIES = {"rate_limited": 0}
REJECTIONS = (RewriteRejectedError, SituationsRejectedError)


def pool_lessons(pool: Path, repos: Path | None) -> list[Lesson]:
    """Every distinct lesson of the pool, or of the listed repositories only."""
    by_repo = distinct(build_lessons._candidates(pool, [])[0])
    wanted = set(json.loads(repos.read_text())) if repos else set(by_repo)
    return [lesson for repo in sorted(wanted & set(by_repo)) for lesson in by_repo[repo]]


def session(run_cap_usd: float) -> SparkSession:
    """The Contributor door with the ledger, the run cap and the pool's provenance."""
    return SparkSession(
        model=MODEL,
        tier=Tier.CONTRIBUTOR,
        run=RUN,
        caps=caps_from_environment(run_cap_usd),
        key=load_meta_key(),
        ledger=Ledger(),
        provenance=(PROVENANCE,),
    )


def asked(spark: SparkSession, prompt: str, label: str) -> SparkReply:
    """One call, retried after a wait on a rate limit (429) only; every retry is counted, and
    the last failure raises."""
    wait = RATE_LIMIT_WAIT_S
    for attempt in range(RATE_LIMIT_TRIES):
        try:
            return spark.chat(prompt, Effort.LOW, label=label)
        except SparkApiError as error:
            if "429" not in str(error) or attempt == RATE_LIMIT_TRIES - 1:
                raise
            RETRIES["rate_limited"] += 1
            time.sleep(wait)
            wait *= 2
    raise AssertionError("unreachable: the loop returns or raises")


def rewrite_one(spark: SparkSession, lesson: Lesson) -> dict:
    """One lesson's trigger sentence, or the reason it was rejected."""
    reply = asked(spark, rewrite_prompt(lesson), "rewrite")
    try:
        return {"lesson_id": lesson.lesson_id, "text": checked_rewrite(lesson, reply.text)}
    except RewriteRejectedError as error:
        return {"lesson_id": lesson.lesson_id, "rejected": str(error)}


def invent_one(spark: SparkSession, lesson: Lesson, count: int) -> dict:
    """One lesson's invented situations, or the reason the reply was rejected."""
    reply = asked(spark, invent_prompt(lesson, count), "invent")
    try:
        found = parsed_situations(lesson, reply.text)
    except SituationsRejectedError as error:
        return {"lesson_id": lesson.lesson_id, "rejected": str(error)}
    return {
        "lesson_id": lesson.lesson_id,
        "situations": list(found.situations),
        "dropped": found.dropped,
    }


def run_all(lessons: list[Lesson], call: Callable[[Lesson], dict], out: Path) -> dict:
    """Call for every lesson not yet in `out`, appending each result as it lands."""
    done = {json.loads(line)["lesson_id"] for line in out.open()} if out.exists() else set()
    todo = [lesson for lesson in lessons if lesson.lesson_id not in done]
    with ThreadPoolExecutor(WORKERS) as pool, out.open("a") as sink:
        for result in pool.map(call, todo):
            sink.write(json.dumps(result) + "\n")
            sink.flush()
    rows = [json.loads(line) for line in out.open()]
    return {
        "lessons": len(rows),
        "rejected": sum("rejected" in row for row in rows),
        "new": len(todo),
        **RETRIES,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("job", choices=("rewrite", "invent"))
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--repos", type=Path)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-cap-usd", type=float, required=True, help="this run's spend cap")
    args = parser.parse_args()
    spark = session(args.run_cap_usd)
    lessons = pool_lessons(args.pool, args.repos)
    if args.job == "rewrite":
        found = run_all(lessons, lambda lesson: rewrite_one(spark, lesson), args.out)
    else:
        found = run_all(lessons, lambda lesson: invent_one(spark, lesson, args.count), args.out)
    print(json.dumps(found))


if __name__ == "__main__":
    main()
