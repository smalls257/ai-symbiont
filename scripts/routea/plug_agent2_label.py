"""PLUG-AGENT-2 labels: Spark says which stored lessons apply to which task, before any agent run.

One call per task with the frozen prompt (`plug_agent2_label_prompt.md`, sha256 pinned in the
prereg): the task's public issue text and its same-repository lessons in template prose. A reply
that is not the exact JSON shape is retried once, then the task is excluded and listed; a failure
is never read as "does not apply". Resumes from the labels file.
Usage: python plug_agent2_label.py <stores.json> <rows.json> <out-dir> --cap-usd 0.8 [--limit N]
"""

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from symbiont.egress.credentials import load_meta_key
from symbiont.egress.policy import Endpoint
from symbiont.egress.spark import Effort, SparkSession
from symbiont.egress.spend import Ledger, SpendCapError, Tier, caps_from_environment
from symbiont.records.schema import Provenance

PROMPT = Path(__file__).with_name("plug_agent2_label_prompt.md")
PUBLIC_ROWS = Provenance(
    dataset="swe-rebench-and-swe-bench-public", license="public", spark_safe=True
)
MODEL = "muse-spark-1.3-contributor"
ISSUE_CHARS = 6000  # frozen: longer issues are cut here, the same for every task
ANSWERS = ("applies", "does_not_apply")
REPLY_TOKENS = 2048
RUN_PREFIX = "plug2-label"


class LabelReplyError(ValueError):
    """The reply is not the one JSON object with one valid label per lesson."""


def lesson_line(index: int, lesson: dict) -> str:
    """The lesson in the template prose the stores carry (no AIDev or private text)."""
    return (
        f"{index}. In {lesson['repo']}, `{lesson['failed']}` failed with {lesson['error']}; "
        f"run `{lesson['fix']}` instead."
    )


def prompt_for(row: dict, lessons: list[dict]) -> str:
    """The frozen prompt filled with one task's issue text and lessons."""
    numbered = "\n".join(lesson_line(i + 1, lesson) for i, lesson in enumerate(lessons))
    text = PROMPT.read_text().replace("{{", "{").replace("}}", "}")
    return (
        text.replace("{repo}", row["repo"])
        .replace("{count}", str(len(lessons)))
        .replace("{issue}", row["problem_statement"][:ISSUE_CHARS])
        .replace("{lessons}", numbered)
    )


def parsed_labels(reply: str, count: int) -> list[str]:
    """The labels in `reply`; raises LabelReplyError unless exactly `count` valid ones."""
    start, end = reply.find("{"), reply.rfind("}")
    try:
        labels = json.loads(reply[start : end + 1])["labels"]
    except (ValueError, KeyError, TypeError) as error:
        raise LabelReplyError(f"no JSON labels: {type(error).__name__}") from error
    if (
        not isinstance(labels, list)
        or len(labels) != count
        or any(x not in ANSWERS for x in labels)
    ):
        raise LabelReplyError("wrong count or an answer outside the two allowed")
    return labels


def session_for(task: str, cap_usd: float) -> SparkSession:
    return SparkSession(
        model=MODEL,
        tier=Tier.CONTRIBUTOR,
        run=f"{RUN_PREFIX}-{task}",
        caps=caps_from_environment(cap_usd),
        key=load_meta_key(),
        provenance=(PUBLIC_ROWS,),
        endpoint=Endpoint.CONTRIBUTOR,
        turn_max_tokens=REPLY_TOKENS,
        temperature=0.0,
    )


def label_task(task: str, row: dict, lessons: list[dict]) -> dict:
    """{"task", "labels"} or {"task", "excluded": reason} after one retry of an unusable reply."""
    prompt = prompt_for(row, lessons)
    reason = ""
    for attempt in (1, 2):
        reply = session_for(task, 0.05).chat(
            prompt, Effort.MINIMAL, f"{RUN_PREFIX}-{task}-a{attempt}"
        )
        try:
            labels = parsed_labels(reply.text, len(lessons))
        except LabelReplyError as error:
            reason = str(error)
            continue
        return {
            "task": task,
            "labels": dict(zip((x["lesson_id"] for x in lessons), labels, strict=True)),
        }
    return {"task": task, "excluded": reason}


def spent() -> float:
    return sum(r["cost_usd"] for r in Ledger().entries() if r["run"].startswith(RUN_PREFIX))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stores", type=Path)
    parser.add_argument("rows", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--cap-usd", type=float, required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    stores = json.loads(args.stores.read_text())
    rows = {r["instance_id"]: r for r in json.loads(args.rows.read_text())}
    log = args.out / "labels.jsonl"
    args.out.mkdir(parents=True, exist_ok=True)
    done = {json.loads(x)["task"] for x in log.read_text().splitlines()} if log.is_file() else set()
    todo = [t for t in sorted(stores) if t not in done][: args.limit]
    lock = threading.Lock()

    def work(task: str) -> None:
        if spent() >= args.cap_usd:
            return
        try:
            found = label_task(task, rows[task], stores[task]["lessons"])
        except SpendCapError as error:
            print(f"cap reached: {error}", file=sys.stderr)
            return
        with lock, log.open("a") as out:
            out.write(json.dumps(found) + "\n")

    with ThreadPoolExecutor(6) as pool:
        list(pool.map(work, todo))
    print(json.dumps({"labeled": len(done) + len(todo), "spent": round(spent(), 3)}))


if __name__ == "__main__":
    main()
