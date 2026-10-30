"""Regenerate .gitleaks-baseline.json: the findings already present in committed history.

Owner-run, and only to ACCEPT findings that are already published (history is never
rewritten). The gate (check_secrets.sh history) fails on any finding not in this file, so
adding to it is a gate change and needs a GATE-CHANGE trailer. Usage: make_secrets_baseline.py
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / ".gitleaks-baseline.json"


def scan_history_without_baseline() -> list[dict]:
    report = ROOT / ".gitleaks-scan.tmp.json"
    command = [
        "gitleaks", "git", "--config", str(ROOT / ".gitleaks.toml"), "--no-banner",
        "--log-level", "error", "--redact", "--report-format", "json",
        "--report-path", str(report), str(ROOT),
    ]  # fmt: skip
    subprocess.run(command, check=False, capture_output=True, text=True)
    found = json.loads(report.read_text() or "[]")
    report.unlink()
    return found


def main() -> int:
    found = scan_history_without_baseline()
    TARGET.write_text(json.dumps(found, indent=2) + "\n")
    summary = Counter((f["RuleID"], f["File"]) for f in found)
    print(f"{len(found)} findings written to {TARGET.name}")
    for (rule, file), count in sorted(summary.items()):
        print(f"  {rule}  {file}  x{count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
