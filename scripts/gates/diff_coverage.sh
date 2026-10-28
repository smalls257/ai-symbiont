#!/usr/bin/env bash
# QG-TST-03 diff coverage. Global coverage can stay flat while every new
# function ships untested; changed lines in src/ must be >= 90% covered, judged against $BASE.
# Fails closed: a missing coverage report means the suite did not run with --cov (exit 2).
#   diff_coverage.sh [COVERAGE.xml]     default: .coverage.xml written by `run.sh full`
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

report="${1:-$ROOT/.coverage.xml}"
need_py_tool diff_cover
[ -s "$report" ] || gate_die "no coverage report at $report: run the suite with --cov-report=xml first"
require_base
exec uv run --no-sync diff-cover "$report" --compare-branch="$BASE" \
  --include 'src/symbiont/**/*.py' --fail-under=90
