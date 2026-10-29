"""Record and check META2's post-run edits to results/meta2.json: two keys renamed, labels added.

The scored run (amendment 1) wrote `verdicts.lines` and `verdicts.claim`; the results gate allows
sentences only under label fields, so they became `verdicts.table` and `verdicts.result`, values
unchanged, and each row gained the prereg's label. The raw file was not kept; `check` restores it
and compares every verdict and table line with the scored run's own log, character for character.
Usage: meta2_rekey.py check --results results/meta2.json --log ~/symbiont-runs/meta2/score2.log
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from meta2_labels import LABELS

RENAMED = {
    ("verdicts", "lines"): ("verdicts", "table"),
    ("verdicts", "claim"): ("verdicts", "result"),
}
LOGGED = re.compile(r" INFO (?:H\d|claim:|[a-zA-Z].* \| )")


def rekey(raw: dict[str, Any]) -> dict[str, Any]:
    """The committed form of a raw scored file: keys renamed, labels added, values unchanged."""
    doc = json.loads(json.dumps(raw))
    for (old_parent, old), (new_parent, new) in RENAMED.items():
        doc[new_parent][new] = doc[old_parent].pop(old)
    for name, windows in doc["rows"].items():
        windows["label"] = LABELS[name]
    return doc


def restore(doc: dict[str, Any]) -> dict[str, Any]:
    """The raw scored file back from the committed form (the inverse of `rekey`)."""
    raw = json.loads(json.dumps(doc))
    for (old_parent, old), (new_parent, new) in RENAMED.items():
        raw[old_parent][old] = raw[new_parent].pop(new)
    for windows in raw["rows"].values():
        windows.pop("label", None)
    raw.pop("results_rekeyed_note", None)
    return raw


def logged_lines(log: Path) -> list[str]:
    """The verdict and table lines the scored run logged, in order."""
    return [
        text.split(" INFO ", 1)[1]
        for text in log.read_text().splitlines()
        if " INFO " in text and LOGGED.search(text) and "meta2-jobs" not in text
    ]


def check(args: argparse.Namespace) -> None:
    """Restore the raw file, match its lines to the run log, and require a round trip."""
    doc = json.loads(Path(args.results).read_text())
    raw = restore(doc)
    lines = [*raw["verdicts"]["lines"], *raw["table"]]
    if lines != logged_lines(Path(args.log)):
        raise SystemExit("the restored verdict and table lines differ from the scored run's log")
    again = rekey(raw)
    again["results_rekeyed_note"] = doc["results_rekeyed_note"]
    if again != doc:
        raise SystemExit("rekey(restore(file)) is not the committed file")
    print(f"ok: {len(lines)} logged lines equal; renamed {sorted(map(str, RENAMED))}; labels added")


def main() -> None:
    """Parse the command line and run one step."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="step", required=True)
    checking = sub.add_parser("check")
    checking.add_argument("--results", required=True)
    checking.add_argument("--log", required=True)
    args = parser.parse_args()
    {"check": check}[args.step](args)
    sys.exit(0)


if __name__ == "__main__":
    main()
