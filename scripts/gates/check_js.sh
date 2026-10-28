#!/usr/bin/env bash
# QG-FE-01 eslint on the dashboard's JavaScript (flat config in dashboard/eslint.config.js,
# versions pinned in dashboard/package-lock.json, installed by `cd dashboard && npm ci`).
# Prevents Forensic Coding: loose equality and unused names are where intent goes to hide.
# Phase 1 scope: changed files; the whole-dashboard count is in baseline.json.
# Fails closed: with files to check, a missing node or pinned eslint exits 2.
#   check_js.sh [FILE ...]        default: changed dashboard/**/*.js
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ "$#" -eq 0 ]; then
  require_base
  files=$(changed_matching '^dashboard/[^n].*\.js$|^dashboard/[^/]*\.js$') \
    || gate_die "cannot list changed files against '$BASE'"
  [ -n "$files" ] || { echo "QG-FE-01: no changed dashboard JavaScript"; exit 0; }
  set -- $files
fi
need_node_tool eslint   # only once there is work: a tree with no dashboard change needs no npm
rel=()
for f in "$@"; do rel+=("${f#dashboard/}"); done
cd "$ROOT/dashboard" || gate_die "no dashboard/ directory"
exec npx --no-install eslint "${rel[@]}"
