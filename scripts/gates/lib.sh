#!/usr/bin/env bash
# Shared by every gate script. Prevents Silent Fallback: a gate that cannot find its
# tool, its config, its base ref or the repo root must fail, never report "nothing to check".
# Source it: `. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"`.
#
# Rule for callers: `gate_die` exits, and an exit inside `$(...)` only leaves the subshell.
# So helpers that run in a command substitution RETURN a non-zero status instead, and the
# caller turns it into a failure: `files=$(changed_files) || gate_die "cannot list files"`.

gate_die() { echo "gate error: $*" >&2; exit 2; }

# Silent Fallback guard: with the default core.quotePath git prints a non-ASCII file name as
# "donn\303\251es.parquet" (quoted, escaped), which no name pattern and no `[ -f ]` recognizes, so
# the file was skipped without a word. Every git call in a gate prints raw UTF-8 names; names git
# still quotes (newline, tab, double quote, backslash) are refused by check_paths.sh, and the
# scripts that need every name exactly read NUL-delimited (-z) output.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.quotePath GIT_CONFIG_VALUE_0=false

# Anchored to the repo root, never to cwd, so a scan from a subdirectory cannot miss files.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || gate_die "not inside a git work tree"
cd "$ROOT" || gate_die "cannot enter $ROOT"

# Phase 1 holds only changed files to the full bar; phase 2 widens this to the whole tree.
BASE="${SYMBIONT_GATE_BASE:-main}"

need_tool() { command -v "$1" >/dev/null 2>&1 || gate_die "required tool not installed: $1 ($2)"; }
need_venv() {
  [ -d "$ROOT/.venv" ] || gate_die "no .venv in $ROOT (a new worktree has none); run: uv sync --group dev"
}
need_py_tool() {
  need_venv
  uv run --no-sync python -c "import $1" >/dev/null 2>&1 \
    || gate_die "python tool not installed: $1 (run: uv sync --group dev)"
}
need_file() { [ -s "$1" ] || gate_die "missing or empty config: $1 (a gate without its config checks nothing)"; }

# require_base: call at top level (never inside $(...)) before any changed-file helper.
require_base() {
  [ "${SYMBIONT_GATE_STAGE:-}" = "pre-commit" ] && return 0
  git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null \
    || gate_die "base ref '$BASE' not found (shallow clone or no main branch?); set SYMBIONT_GATE_BASE"
}

# changed_files: staged files at commit time, otherwise everything this branch changed against
# $BASE plus uncommitted and untracked work, deleted files excluded. Returns 2 on any git
# failure so a caller's `|| gate_die` fires; it never prints a partial list as success.
changed_files() {
  local committed worktree untracked
  if [ "${SYMBIONT_GATE_STAGE:-}" = "pre-commit" ]; then
    git diff --cached --name-only --diff-filter=ACMR || return 2
    return 0
  fi
  git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null || return 2
  committed=$(git diff --name-only --diff-filter=ACMR "$BASE"...HEAD) || return 2
  worktree=$(git diff --name-only --diff-filter=ACMR HEAD) || return 2
  untracked=$(git ls-files --others --exclude-standard) || return 2
  printf '%s\n%s\n%s\n' "$committed" "$worktree" "$untracked" | sort -u | while IFS= read -r f; do
    if [ -n "$f" ] && [ -f "$f" ]; then echo "$f"; fi
  done
}

# changed_matching <extended-regex>: changed files whose path matches. Status 2 on failure.
changed_matching() {
  local all
  all=$(changed_files) || return 2
  printf '%s\n' "$all" | grep -E "$1" || [ $? -eq 1 ]
}
