#!/usr/bin/env bash
# One-time hook activation: points git at the tracked hooks in scripts/hooks. Worktrees share
# the main repository's config, so this arms every worktree at once; run it deliberately,
# after merges, not while other agents are mid-commit. Undo with:
#   git config --unset core.hooksPath
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
for hook in pre-commit commit-msg pre-push; do
  [ -f "scripts/hooks/$hook" ] || { echo "missing scripts/hooks/$hook" >&2; exit 2; }
  chmod +x "scripts/hooks/$hook"
done
git config core.hooksPath scripts/hooks
echo "hooks armed: core.hooksPath = scripts/hooks (pre-commit: changed-file gates plus touched-package tests, commit-msg: GATE-CHANGE check, pre-push: full gates)"
