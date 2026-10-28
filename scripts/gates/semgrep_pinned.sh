#!/usr/bin/env bash
# QG-SAST-02 launcher (custom rules; the registry packs are QG-SAST-01, semgrep_registry.sh). Unpinned, a semgrep update would change the
# verdict with no commit explaining why. Refuses to run any version but the one in
# .semgrep/VERSION, naming both. Metrics off, no version check, local rules only: no network.
#   semgrep_pinned.sh [FILE ...]        scan the files with the repo's custom rules
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_pinned_semgrep
ls "$ROOT"/.semgrep/symbiont/*.yaml >/dev/null 2>&1 || gate_die "no rules in .semgrep/symbiont/"

if [ "$#" -eq 0 ]; then
  require_base
  files=$(changed_matching '\.(py|sh)$') || gate_die "cannot list changed files against '$BASE'"
  files=$(printf '%s\n' "$files" | grep -vE '^(tests/fixtures/|spikes/|$)' || [ $? -eq 1 ]) \
    || gate_die "file selection failed"
  [ -n "$files" ] || { echo "QG-SAST-02: no changed python or shell files"; exit 0; }
  set -- $files
fi
exec uv run --no-sync semgrep scan --metrics=off --disable-version-check --quiet --error \
  --config "$ROOT/.semgrep/symbiont" "$@"
