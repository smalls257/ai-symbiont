#!/usr/bin/env bash
# QG-FE-03 HTML validity with html-validate (pinned in dashboard/package-lock.json). Advisory:
# exit 1 means errors were found, and run.sh reports them without failing the run. Errors
# only; warnings are ignored. dashboard/.htmlvalidate.mjs switches off the style rules
# (inline style, void-element and doctype case) that generated reports trip on without being invalid.
# Fails closed: with files to check, a missing node or html-validate, or no report, exits 2.
#   check_html.sh [FILE ...]      default: changed dashboard/ and docs/ .html files
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_venv
if [ "$#" -eq 0 ]; then
  require_base
  files=$(changed_matching '^(dashboard|docs)/.*\.html$') || gate_die "cannot list changed files against '$BASE'"
  [ -n "$files" ] || { echo "QG-FE-03: no changed HTML"; exit 0; }
  set -- $files
fi
need_node_tool html-validate   # only once there is work
abs=()
for f in "$@"; do case "$f" in /*) abs+=("$f") ;; *) abs+=("$ROOT/$f") ;; esac; done
report="$(mktemp)" || gate_die "cannot create a temp file"
trap 'rm -f "$report"' EXIT
(cd "$ROOT/dashboard" && npx --no-install html-validate --config .htmlvalidate.mjs \
  -f "json=$report" "${abs[@]}") >/dev/null 2>&1
[ -s "$report" ] || gate_die "html-validate wrote no report"
uv run --no-sync python "$ROOT/scripts/gates/check_html_report.py" "$report"
