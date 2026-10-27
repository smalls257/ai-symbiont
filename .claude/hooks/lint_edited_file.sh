#!/usr/bin/env bash
# QG-AI-01 PostToolUse hook (Write|Edit). Prevents Silent Fallback: an agent that edits a
# file and never hears that it broke the lint, complexity or nesting caps. The hook REPORTS:
# findings go to stderr with exit 2, which Claude Code feeds back to the agent. It never
# ends in `|| true`, and a failure to run the tools is itself a reported failure.
# Budget about 2 s: ruff, lizard and the nesting check run on the one edited file;
# semgrep (cold start about 7 s) runs in the pre-commit gate instead.
set -uo pipefail

file=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))') \
  || { echo "QG-AI-01: could not read the hook input" >&2; exit 2; }
case "$file" in *.py) ;; *) exit 0 ;; esac
[ -f "$file" ] || exit 0

root=$(git -C "$(dirname "$file")" rev-parse --show-toplevel 2>/dev/null) \
  || { echo "QG-AI-01: $file is not inside a git work tree" >&2; exit 2; }
cd "$root" || exit 2
rel="${file#"$root"/}"
[ -d .venv ] || { echo "QG-AI-01: no .venv in $root (a new worktree has none); run: uv sync --group dev" >&2; exit 2; }
case "$rel" in tests/fixtures/*|spikes/*|.claude/*) exit 0 ;; esac

findings=""
note() { findings="$findings$*"$'\n'; }

# Formatting is mechanical, so fix it rather than nag; report only if the tool itself fails.
fmt=$(uv run --no-sync ruff format "$rel" 2>&1) || note "ruff format failed: $fmt"
chk=$(uv run --no-sync ruff check "$rel" 2>&1) || note "$chk"
cpx=$(scripts/gates/check_complexity.sh "$rel" 2>&1) || note "$cpx"

if [ -n "$findings" ]; then
  echo "QG-AI-01: findings in $rel (fix the code, never the gate):" >&2
  printf '%s' "$findings" >&2
  exit 2
fi
exit 0
