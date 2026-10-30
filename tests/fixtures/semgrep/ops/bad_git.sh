#!/usr/bin/env bash
set -euo pipefail
git stash # expect: sym-no-git-rewrite
git commit --amend -m "again" # expect: sym-no-git-rewrite
cd /tmp && git reset --hard # expect: sym-no-git-rewrite
git rebase main # expect: sym-no-git-rewrite
git push --force origin main # expect: sym-no-git-rewrite
git add -A # expect: sym-no-git-rewrite
git add . # expect: sym-no-git-rewrite
if true; then git stash pop; fi # expect: sym-no-git-rewrite
