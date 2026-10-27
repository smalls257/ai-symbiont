#!/usr/bin/env bash
set -euo pipefail
git add scripts/gates/run.sh
git commit -m "Explicit paths, no rewrite"
git diff --cached --name-only
git add ./ops/notes.txt
grep -E 'git (stash|reset|rebase)' hook_patterns.txt
echo "never git stash in here"
