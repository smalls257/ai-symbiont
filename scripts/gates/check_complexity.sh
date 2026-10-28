#!/usr/bin/env bash
# QG-CPX-01/02 function size. Caps are per function, so the
# waiver is per function too: `path.py:function` lines in the delete-only whitelist.
#   pure core (records, miner, core, routeb): CCN <= 10, NLOC <= 30, params <= 5
#   everything else in src/, scripts/, ops/:  CCN <= 12, NLOC <= 40, params <= 5
#   tests/:                                    NLOC <= 60 per function
#   nesting <= 3 in src/, scripts/, ops/ (AST check; lizard's own is unusable here)
# No carve-out for tooling: the gate scripts obey the caps they enforce.
# Usage: check_complexity.sh [FILE.py ...]   default: changed python files.
# Fails closed: a missing lizard, whitelist or file list exits 2, never 0.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

WL="$ROOT/.lizard-whitelist.txt"
need_file "$WL"
need_py_tool lizard

if [ "$#" -gt 0 ]; then
  files=$(printf '%s\n' "$@")
else
  require_base
  files=$(changed_matching '\.py$') || gate_die "cannot list changed files against '$BASE'"
fi
pure_re='^src/symbiont/(core|miner|records|routeb)/'
pure=$(printf '%s\n' "$files" | grep -E "$pure_re" || [ $? -eq 1 ]) || gate_die "file selection failed"
edge=$(printf '%s\n' "$files" | grep -E '^(src/symbiont|scripts|ops)/' | grep -vE "$pure_re" || [ $? -eq 1 ]) \
  || gate_die "file selection failed"
tests=$(printf '%s\n' "$files" | grep -E '^tests/' | grep -vE '^tests/fixtures/' || [ $? -eq 1 ]) \
  || gate_die "file selection failed"
nested=$(printf '%s\n%s\n' "$pure" "$edge" | grep . || [ $? -eq 1 ]) || gate_die "file selection failed"

status=0
lizard() { uv run --no-sync lizard "$@"; }
# shellcheck disable=SC2086
{
  [ -z "$pure" ] || lizard $pure -C 10 -T nloc=30 -a 5 -W "$WL" -w || status=1
  [ -z "$edge" ] || lizard $edge -C 12 -T nloc=40 -a 5 -W "$WL" -w || status=1
  [ -z "$tests" ] || lizard $tests -C 30 -T nloc=60 -a 12 -W "$WL" -w || status=1
  [ -z "$nested" ] || uv run --no-sync python scripts/gates/check_nesting.py $nested || status=1
}
[ "$status" -eq 0 ] && echo "QG-CPX: OK"
exit "$status"
