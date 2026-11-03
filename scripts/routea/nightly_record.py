"""Record which lessons a repository's nightly adapter was trained on, for a trainer run elsewhere.

`symbiont nightly` trains on this machine and writes the record itself; this script is for a
trainer that ran on another host (the CUDA desktop).
Usage: TRAINER_CMD && nightly_record.py --store DB --project P --out D --judge-url U
The trainer is the GPU job of plug/round3 scripts/routea/plug_r4.sh `nightly` (fixed base, general
judge, all lessons so far, 15% habit replay, never stacked). The `&&` writes the record only after
it exits 0; a failed night leaves the older record, which then reads as stale.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from symbiont.miner.twins import merge_twins
from symbiont.service.nightly import NightlyRecord, lessons_digest, write_record
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
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    record = NightlyRecord(lessons_digest(lessons), args.judge_url, len(lessons), stamp, "external")
    write_record(args.out, args.project, record)
    print(f"nightly_record: {args.project} trained on {len(lessons)} lessons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
