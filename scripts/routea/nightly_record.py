"""Record which lessons a repository's nightly adapter was trained on.

Usage: TRAINER_CMD && nightly_record.py --store DB --project P --out D --judge-url U
The trainer is the GPU job of plug/round3 scripts/routea/plug_r4.sh `nightly` (fixed base, general
judge, all lessons so far, 15% habit replay, never stacked). The `&&` writes the record only after
it exits 0; a failed night leaves the older record, which then reads as stale.
"""

import argparse
import json
import sys
from pathlib import Path

from symbiont.miner.twins import merge_twins
from symbiont.service.nightly import RECORD, lessons_digest
from symbiont.store.local import Store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--judge-url", required=True)
    args = parser.parse_args()
    lessons = merge_twins(Store.open(args.store).lessons(args.project))
    if not lessons:
        print(f"nightly_record: {args.project} has no lessons to train on", file=sys.stderr)
        return 1
    target = args.out / args.project
    target.mkdir(parents=True, exist_ok=True)
    record = {"lessons_digest": lessons_digest(lessons), "judge_url": args.judge_url}
    (target / RECORD).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(f"nightly_record: {args.project} trained on {len(lessons)} lessons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
