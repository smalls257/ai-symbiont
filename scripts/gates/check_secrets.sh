#!/usr/bin/env bash
# QG-SEC-01 / QG-SEC-02 secrets and private infrastructure. Guards against a
# scan that "found nothing" because gitleaks or its config was missing.
#   check_secrets.sh files [FILE ...]   scan the working copy of those files (default: changed)
#   check_secrets.sh staged             scan the staged diff (pre-commit)
#   check_secrets.sh history            scan commits not on $BASE (phase 1 scope)
#   SYMBIONT_GATE_HISTORY=all check_secrets.sh history   scan every commit (before a push)
# A leaked credential is rotated first; history is never rewritten (project git rules).
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_tool gitleaks "brew install gitleaks"
need_file "$ROOT/.gitleaks.toml"
CONFIG="$ROOT/.gitleaks.toml"
scan=(--config "$CONFIG" --redact --no-banner --log-level warn --exit-code 1)

mode="${1:-files}"; shift || true
case "$mode" in
  staged) gitleaks git --pre-commit --staged "${scan[@]}" "$ROOT" ;;
  history)
    # Always the whole history, against a baseline of the findings already published in
    # committed history: old ones are reported by the baseline file, never hidden; any new one
    # fails. (History is never rewritten; the owner publishes from a fresh repo.)
    need_file "$ROOT/.gitleaks-baseline.json"
    gitleaks git --baseline-path "$ROOT/.gitleaks-baseline.json" "${scan[@]}" "$ROOT" ;;
  files)
    if [ "$#" -gt 0 ]; then files=$(printf '%s\n' "$@"); else
      require_base
      files=$(changed_files) || gate_die "cannot list changed files against '$BASE'"
    fi
    status=0
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      gitleaks dir "${scan[@]}" "$f" || status=1
    done <<< "$files"
    exit "$status" ;;
  *) gate_die "unknown mode '$mode' (files|staged|history)" ;;
esac
