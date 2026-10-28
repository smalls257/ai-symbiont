"""QG-TST-01 test-count floor and zero skips. Prevents Paper Tiger: a suite that collected
nothing (or skipped what it could not run) is green and proves nothing.

Reads a pytest --junitxml report and fails when
  * the report is missing or unreadable (the suite did not run),
  * tests < the floor in scripts/gates/test-floor.txt,
  * any test was skipped (a skip hides a dependency that should be a periphery mark or a
    fixture; there is no waiver, so delete or fix the test),
  * any test failed or errored.
The floor only ratchets up: `--update` raises it to 95 percent of this green run, never lowers.

Usage: assert_suite_floor.py REPORT.xml [--update]
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from defusedxml.ElementTree import parse as parse_xml_defensively  # QG-SAST-01

FLOOR_FILE = Path(__file__).with_name("test-floor.txt")
RATCHET_SHARE = 0.95


class FloorGateError(RuntimeError):
    """The gate cannot judge the suite (missing report or floor file)."""


@dataclass(frozen=True)
class SuiteCounts:
    tests: int
    skipped: int
    failed: int


def read_counts(report: Path) -> SuiteCounts:
    if not report.is_file():
        raise FloorGateError(f"no junit report at {report}: the suite did not run")
    root = parse_xml_defensively(report).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if not suites:
        raise FloorGateError(f"{report} holds no testsuite")
    return SuiteCounts(
        tests=sum(int(s.get("tests", 0)) for s in suites),
        skipped=sum(int(s.get("skipped", 0)) for s in suites),
        failed=sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites),
    )


def read_floor(path: Path = FLOOR_FILE) -> int:
    if not path.is_file():
        raise FloorGateError(f"missing floor file {path}")
    return int(path.read_text().split("#", 1)[0].strip())


def violations(counts: SuiteCounts, floor: int) -> list[str]:
    found = []
    if counts.tests < floor:
        found.append(
            f"{counts.tests} tests ran, floor is {floor}: tests were deleted or not collected"
        )
    if counts.skipped:
        found.append(f"{counts.skipped} skipped: fix or delete the test, skips have no waiver")
    if counts.failed:
        found.append(f"{counts.failed} failed or errored")
    return found


def ratcheted_floor(counts: SuiteCounts, floor: int) -> int:
    return max(floor, int(counts.tests * RATCHET_SHARE))


def main(argv: list[str]) -> int:
    paths = [a for a in argv if not a.startswith("--")]
    if len(paths) != 1:
        raise FloorGateError("usage: assert_suite_floor.py REPORT.xml [--update]")
    counts = read_counts(Path(paths[0]))
    floor = read_floor()
    problems = violations(counts, floor)
    for problem in problems:
        print(f"QG-TST-01: {problem}", file=sys.stderr)
    if problems:
        return 1
    if "--update" in argv:
        FLOOR_FILE.write_text(f"{ratcheted_floor(counts, floor)}  # only ever raised by --update\n")
    print(f"QG-TST-01: OK ({counts.tests} tests, floor {floor}, 0 skipped)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except FloorGateError as err:
        print(f"gate error: {err}", file=sys.stderr)
        sys.exit(2)
