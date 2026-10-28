"""QG-FE-03 verdict from an html-validate JSON report: errors count, warnings do not.

Exit 1 when any error is found (the caller treats FE-03 as advisory), 2 when the report cannot
be read. Prints one line per error as path:line:col rule, then a summary.
"""

import json
import sys
from pathlib import Path

EXIT_ERRORS = 1
EXIT_CANNOT_JUDGE = 2
ERROR_SEVERITY = 2


def describe(result: dict, msg: dict) -> str:
    where = f"{Path(result['filePath']).name}:{msg['line']}:{msg['column']}"
    return f"{where} {msg['ruleId']}: {msg['message']}"


def errors_in(report: list[dict]) -> list[str]:
    return [
        describe(result, msg)
        for result in report
        for msg in result["messages"]
        if msg["severity"] == ERROR_SEVERITY
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return EXIT_CANNOT_JUDGE
    try:
        report = json.loads(Path(argv[1]).read_text())
    except (OSError, json.JSONDecodeError) as err:
        print(f"QG-FE-03 cannot judge: {err}", file=sys.stderr)
        return EXIT_CANNOT_JUDGE
    found = errors_in(report)
    for line in found:
        print(line)
    print(f"QG-FE-03: {len(found)} error(s) in {len(report)} file(s) with findings (advisory)")
    return EXIT_ERRORS if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
