#!/usr/bin/env bash
# QG-TST-05 mutation testing of the pure core (core/ and miner/signals/) with mutmut. Prevents
# Paper Tiger: tests that run the code and assert nothing. A release and weekly-CI target, NOT
# part of run.sh: a run is minutes, and the inner loop is seconds.
#   scripts/gates/mutation.sh        fresh run, prints the killed share and the survivors;
#                                    exits 1 under the 80% bar, 2 if mutmut could not run
# Fresh each time (mutants/ is removed): a cached verdict would hide a test that stopped
# killing a mutant. Config: [tool.mutmut] in pyproject.toml.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_py_tool mutmut
grep -q '^\[tool.mutmut\]' "$ROOT/pyproject.toml" || gate_die "no [tool.mutmut] in pyproject.toml"
rm -rf "$ROOT/mutants"
results="$(mktemp)" || gate_die "cannot create a temp file"
trap 'rm -f "$results"' EXIT
uv run --no-sync mutmut run >/dev/null 2>&1 || gate_die "mutmut run failed (survivors exit 0 in 3.8.0, so this is a crash)"
[ -d "$ROOT/mutants" ] || gate_die "mutmut produced no mutants/ directory"
uv run --no-sync mutmut export-cicd-stats >/dev/null 2>&1 || gate_die "mutmut export-cicd-stats failed"
uv run --no-sync mutmut results > "$results" 2>&1 || gate_die "mutmut results failed"
uv run --no-sync python "$ROOT/scripts/gates/mutation_score.py" "$ROOT/mutants/mutmut-cicd-stats.json" "$results"
