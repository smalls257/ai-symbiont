"""Each custom semgrep rule fires on its bad fixtures and stays quiet on its good ones.

The fixtures under tests/fixtures/semgrep mirror a repo tree (src/symbiont/core/..., ops/...)
and mark every line a rule must report with `# expect: <rule-id>`. The test compares the
reported (file, line, rule) set to the expected set, so a rule that over-fires fails just as
a rule that never fires does. A false positive is fixed in the rule, with a case here.

Fixtures are copied to a temp dir first: inside this git repo semgrep's default ignore list
skips tests/, and the rules' path scopes are anchored to the scan root.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "semgrep"
RULES = REPO / ".semgrep" / "symbiont"
SEMGREP = Path(sys.executable).parent / "semgrep"
EXPECT = re.compile(r"#\s*expect:\s*((?:sym-[\w-]+[\s,]*)+)")

pytestmark = pytest.mark.periphery


def _marked_lines(path: Path) -> set[tuple[str, int, str]]:
    marked = set()
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if match := EXPECT.search(line):
            rel = str(path.relative_to(FIXTURES))
            marked |= {(rel, number, rule) for rule in re.findall(r"sym-[\w-]+", match.group(1))}
    return marked


def _expected() -> set[tuple[str, int, str]]:
    found = set()
    for path in FIXTURES.rglob("*"):
        if path.is_file():
            found |= _marked_lines(path)
    return found


@pytest.fixture(scope="module")
def reported(tmp_path_factory) -> set[tuple[str, int, str]]:
    tree = tmp_path_factory.mktemp("semgrep_tree") / "tree"
    shutil.copytree(FIXTURES, tree)
    out = subprocess.run(
        [
            str(SEMGREP),
            "scan",
            "--metrics=off",
            "--disable-version-check",
            "--quiet",
            "--json",
            "--config",
            str(RULES),
            ".",
        ],
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(out.stdout)
    assert report["errors"] == [], report["errors"]
    return {
        (r["path"], r["start"]["line"], r["check_id"].rsplit(".", 1)[-1]) for r in report["results"]
    }


def test_rules_report_exactly_the_marked_lines(reported):
    expected = _expected()
    assert sorted(reported - expected) == [], "false positives (rule fires on a good line)"
    assert sorted(expected - reported) == [], "false negatives (rule misses a bad line)"


def test_every_rule_has_a_firing_fixture():
    rule_ids = set(
        re.findall(
            r"^  - id: (sym-[\w-]+)",
            "".join(p.read_text() for p in RULES.glob("*.yaml")),
            flags=re.M,
        )
    )
    fired = {rule for _, _, rule in _expected()}
    assert rule_ids - fired == set(), "rules with no bad fixture prove nothing"
    assert fired - rule_ids == set(), "fixture expects a rule that does not exist"


def test_semgrep_version_matches_the_pin():
    pinned = (REPO / ".semgrep" / "VERSION").read_text().strip()
    out = subprocess.run([str(SEMGREP), "--version"], capture_output=True, text=True, check=True)
    assert out.stdout.strip().splitlines()[-1] == pinned
