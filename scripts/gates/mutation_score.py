"""QG-TST-05: killed share of mutmut mutants against the 80% bar, with the survivors listed.

Run by mutation.sh at release, not by run.sh. Exit 0 at the bar, 1 below it, 2 no stats.
Usage: mutation_score.py [STATS.json] [RESULTS.txt]
"""

import json
import sys
from pathlib import Path

BAR_PERCENT = 80.0  # QG-TST-05 in docs/standards/quality-gates.html
DEFAULT_STATS = Path("mutants/mutmut-cicd-stats.json")


def killed_share(stats: dict) -> float:
    """Percent of mutants the tests noticed. A timeout counts as noticed (an infinite loop)."""
    total = stats["total"]
    if total <= 0:
        raise ValueError("mutmut reports zero mutants: the core was not mutated")
    return 100.0 * (stats["killed"] + stats["timeout"]) / total


def survivors(results_text: str) -> list[str]:
    return [
        ln.split(":")[0].strip() for ln in results_text.splitlines() if ln.endswith(": survived")
    ]


def main(argv: list[str]) -> int:
    stats_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_STATS
    try:
        stats = json.loads(stats_path.read_text())
        share = killed_share(stats)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as err:
        print(f"QG-TST-05 cannot judge: {err}", file=sys.stderr)
        return 2
    if len(argv) > 2:
        for name in survivors(Path(argv[2]).read_text()):
            print(f"survived {name}")
    verdict = "OK" if share >= BAR_PERCENT else "BELOW THE BAR"
    detail = ", ".join(
        f"{key} {stats[key]}" for key in ("killed", "survived", "timeout", "no_tests", "total")
    )
    print(f"QG-TST-05: {share:.1f}% killed ({detail}); bar {BAR_PERCENT:.0f}%: {verdict}")
    return 0 if share >= BAR_PERCENT else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
