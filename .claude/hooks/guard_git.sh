#!/usr/bin/env bash
# QG-AI-02 PreToolUse hook (Bash). Enforces the project git rules before the command runs:
# history is the record, so no stash, amend, reset, rebase or force-push, and no blanket
# `add -A` / `add .` (commit explicit paths). An implementer working in a worktree under
# .claude/worktrees/ may also never push: publishing is the owner's step.
# Exit 2 blocks the call; stderr names the rule.
set -uo pipefail

command=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))') \
  || { echo "QG-AI-02: could not read the hook input" >&2; exit 2; }

# `git` in command position: line start or after ; & | ( { so prose that merely mentions it passes.
GIT='(^|[;&|({]|&&|\|\|)[[:space:]]*git[[:space:]]+((-C|-c)[[:space:]]+[^[:space:]]+[[:space:]]+|--no-pager[[:space:]]+|-p[[:space:]]+)*'
deny() { echo "QG-AI-02: blocked: $1 (project git rules). Command: $command" >&2; exit 2; }

echo "$command" | grep -qE "${GIT}stash([[:space:]]|\$)" && deny "git stash; use a temporary WIP commit"
echo "$command" | grep -qE "${GIT}commit[^;&|]*--amend" && deny "git commit --amend; make a new commit"
echo "$command" | grep -qE "${GIT}reset([[:space:]]|\$)" && deny "git reset; history is never rewritten"
echo "$command" | grep -qE "${GIT}rebase([[:space:]]|\$)" && deny "git rebase; history is never rewritten"
echo "$command" | grep -qE "${GIT}push[^;&|]*(--force|[[:space:]]-f([[:space:]]|\$))" && deny "force-push"
echo "$command" | grep -qE "${GIT}add[[:space:]]+(-A|--all|\.)([[:space:]]|\$)" && deny "blanket git add; name explicit paths"
if echo "$command" | grep -qE "${GIT}push([[:space:]]|\$)"; then
  case "${PWD:-}" in
    */.claude/worktrees/*) deny "git push from an agent worktree; the owner publishes" ;;
  esac
fi
exit 0
