#!/usr/bin/env bash
# The one entry point for the quality gates (docs/standards/quality-gates.html). The edit
# hook, pre-commit, pre-push and CI all call this script, so there is one definition of
# "green". Prevents Paper Tiger (green that proves nothing) and Silent Fallback (a gate that
# never ran): a missing tool, config, venv or base ref is a failure, never a skipped check.
#
#   scripts/gates/run.sh fast   (pre-commit: scoped unit tests only; pre-push/manual: whole suite)
#                               changed files vs $SYMBIONT_GATE_BASE (default main): secrets,
#                               private terms, result-file content, paths, gate integrity, ruff, size, naming, semgrep, the whole
#                               test suite with its count floor, claim tags, result rows
#   scripts/gates/run.sh full   fast, plus history scan against the baseline, import-linter,
#                               mypy on changed files, coverage report, lockfile
#
# Phase 1 holds changed files to the full bar; existing offenders are counted in
# scripts/gates/baseline.json and cleaned in phase 2. Exit 0 all green, 1 a gate failed,
# 2 the gates could not run. Every gate appends one line to .gate-runs.jsonl.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

mode="${1:-}"
case "$mode" in fast|full) ;; *) gate_die "usage: run.sh fast|full" ;; esac
stage="${SYMBIONT_GATE_STAGE:-$mode}"
log="$ROOT/.gate-runs.jsonl"
failed=""
suite_args=""   # full adds a coverage report; the floor is judged on the same single run

require_everything() {
  need_tool uv "https://docs.astral.sh/uv/"
  need_tool gitleaks "brew install gitleaks"
  need_venv
  for tool in ruff lizard semgrep mypy importlinter pytest_cov; do need_py_tool "$tool"; done
  for cfg in pyproject.toml .naming-waivers.txt .gitleaks.toml .gitleaks-baseline.json .semgrep/VERSION \
             .importlinter .lizard-whitelist.txt scripts/gates/test-floor.txt; do
    need_file "$ROOT/$cfg"
  done
  require_base
}

# gate <id> <command...>: run, show output only on failure, log id/stage/duration/verdict.
gate() {
  local id="$1"; shift
  local started=$SECONDS output rc verdict
  output=$("$@" 2>&1); rc=$?
  verdict=pass; [ "$rc" -eq 0 ] || verdict=fail
  printf '{"ts":"%s","gate":"%s","stage":"%s","duration_s":%s,"verdict":"%s"}\n' \
    "$(date -u +%FT%TZ)" "$id" "$stage" "$((SECONDS - started))" "$verdict" >> "$log"
  if [ "$rc" -eq 0 ]; then
    echo "ok    $id ($((SECONDS - started))s)"
  else
    echo "FAIL  $id"; printf '%s\n' "$output" | sed 's/^/      /'; failed="$failed $id"
  fi
}

# Files each gate sees. Fixtures hold deliberate violations; spikes are throwaway probes.
select_files() {
  all=$(changed_files) || gate_die "cannot list changed files against '$BASE'"
  py=$(printf '%s\n' "$all" | grep -E '\.py$' | grep -vE '^(tests/fixtures/|spikes/|\.claude/)' || [ $? -eq 1 ]) \
    || gate_die "file selection failed"
  # one size and naming bar for src, scripts and ops: no tooling carve-out
  named=$(printf '%s\n' "$py" | grep -E '^(src|scripts|ops)/' || [ $? -eq 1 ]) || gate_die "file selection failed"
  checked=$(printf '%s\n' "$py" | grep -E '^(src|scripts|ops|tests)/' || [ $? -eq 1 ]) || gate_die "file selection failed"
  docs=$(printf '%s\n' "$all" | grep -E '^(docs/|results/|README\.md$|prereg/)' || [ $? -eq 1 ]) \
    || gate_die "file selection failed"
}

run_suite() {   # the whole suite is seconds, so the floor is always judged on a full run
  local report; report="$(mktemp "${TMPDIR:-/tmp}/symbiont-junit.XXXXXX")"
  uv run --no-sync pytest -q -p no:cacheprovider --junitxml="$report" "$@" || { rm -f "$report"; return 1; }
  uv run --no-sync python scripts/gates/assert_suite_floor.py "$report"; local rc=$?
  rm -f "$report"; return $rc
}

# Pre-commit stays fast: the unit tests for the packages a commit touches, plus the boundary
# tests. The whole suite, its count floor, the run.sh tests and the history scan run at pre-push.
scoped_unit_tests() {
  local targets="tests/test_boundaries.py" pkg
  for pkg in $(printf '%s\n' "$all" | sed -nE 's#^src/symbiont/([a-z0-9_]+)/.*#\1#p; s#^scripts/([a-z0-9_]+)/.*#\1#p' | sort -u); do
    if [ "$pkg" = "gates" ] || [ "$pkg" = "hooks" ]; then pkg="gates"; fi
    [ -d "tests/$pkg" ] && targets="$targets tests/$pkg"
  done
  targets="$targets $(printf '%s\n' "$all" | grep -E '^tests/.*test_[^/]*\.py$' | tr '\n' ' ')"
  # shellcheck disable=SC2086
  uv run --no-sync pytest -q -p no:cacheprovider --ignore=tests/gates/test_run_script.py --ignore=tests/gates/test_check_export.py $targets
}

private_terms_in_changed_files() {   # names go NUL-delimited: a space or quote cannot split one
  printf '%s\n' "$all" | tr '\n' '\0' | uv run --no-sync python scripts/gates/check_private_terms.py files0
}

fast_gates() {
  gate QG-SEC-03 scripts/gates/check_paths.sh
  gate QG-SEC-04 uv run --no-sync python scripts/gates/check_results_content.py
  if [ "${SYMBIONT_GATE_STAGE:-}" = "pre-commit" ]; then
    gate QG-SEC-01 scripts/gates/check_secrets.sh staged
    gate QG-SEC-05 uv run --no-sync python scripts/gates/check_private_terms.py staged
  else
    gate QG-SEC-01 scripts/gates/check_secrets.sh files
    gate QG-SEC-05 private_terms_in_changed_files
    gate QG-GATE-01 uv run --no-sync python scripts/gates/check_gate_integrity.py
  fi
  if [ -n "$py" ]; then
    # shellcheck disable=SC2086
    gate QG-LINT-02 uv run --no-sync ruff format --check $py
    # shellcheck disable=SC2086
    gate QG-LINT-01 uv run --no-sync ruff check $py
  fi
  if [ -n "$checked" ]; then
    # shellcheck disable=SC2086
    gate QG-CPX-01 scripts/gates/check_complexity.sh $checked
    # shellcheck disable=SC2086
    gate QG-CPX-03 uv run --no-sync python scripts/gates/check_file_length.py $checked
  fi
  # shellcheck disable=SC2086
  [ -z "$named" ] || gate QG-RD-02 uv run --no-sync python scripts/gates/check_naming.py $named
  gate QG-SAST-02 scripts/gates/semgrep_pinned.sh
  if [ "$stage" = "pre-commit" ]; then
    gate QG-TST-02 scoped_unit_tests
  else
    # shellcheck disable=SC2086
    gate QG-TST-01 run_suite $suite_args
  fi
  # shellcheck disable=SC2086
  [ -z "$docs" ] || gate QG-SCI-02 uv run --no-sync python scripts/gates/check_claims.py $docs
  if printf '%s\n' "$all" | grep -qE '^results/.*\.json$'; then
    gate QG-SCI-03 uv run --no-sync python scripts/gates/check_results.py
  fi
}

full_gates() {
  gate QG-SEC-02 scripts/gates/check_secrets.sh history
  gate QG-ARC-01 uv run --no-sync lint-imports
  gate QG-DEP-03 uv lock --check
  local typed; typed=$(printf '%s\n' "$all" | grep -E '^src/symbiont/.*\.py$' || [ $? -eq 1 ]) \
    || gate_die "file selection failed"
  # shellcheck disable=SC2086
  [ -z "$typed" ] || gate QG-TYP-01 uv run --no-sync mypy $typed
  # every loosening on this branch is listed on every full run, for the human to see
  uv run --no-sync python scripts/gates/check_gate_integrity.py --list \
    || { echo "FAIL  QG-GATE-01 report"; failed="$failed QG-GATE-01-report"; }
}

require_everything
select_files
echo "gates: $mode on $(printf '%s\n' "$all" | grep -c . || true) changed file(s) vs $BASE"
[ "$mode" = "full" ] && suite_args="--cov --cov-report=term --cov-fail-under=0"
fast_gates
[ "$mode" = "full" ] && full_gates
if [ -n "$failed" ]; then echo "RED:$failed"; exit 1; fi
echo "GREEN"
