#!/usr/bin/env bash
# QG-SAST-01 semgrep registry packs p/python, p/bandit, p/secrets. Prevents Forensic Coding
# (pinned semgrep version and a stamped snapshot, so the verdict names what judged it) and
# Silent Fallback (a missing or foreign snapshot is a failure, never a skipped scan).
# Blocks on ERROR, advisory on WARNING (check_registry_findings.py). No network: the snapshot
# comes from fetch_semgrep_packs.sh and is gitignored (see the reason there).
#   semgrep_registry.sh            changed files vs $BASE (fast)
#   semgrep_registry.sh --tree     every tracked and untracked-unignored file (full)
#   semgrep_registry.sh FILE ...   those files
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PACKS="$ROOT/.semgrep/registry"
require_pinned_semgrep
for pack in python bandit secrets STAMP; do
  [ -s "$PACKS/$pack.yaml" ] || [ -s "$PACKS/$pack" ] \
    || gate_die "registry snapshot missing ($PACKS/$pack): run scripts/gates/fetch_semgrep_packs.sh"
done
stamp="$(cat "$PACKS/STAMP")"
case "$stamp" in
  "semgrep=$SEMGREP_PINNED "*) ;;
  *) gate_die "snapshot was fetched under another semgrep ($stamp); pinned $SEMGREP_PINNED; refetch" ;;
esac

skip='^(tests/fixtures/|spikes/|uv\.lock$|\.semgrep/registry/|$)'   # fixtures hold planted violations
if [ "${1:-}" = "--tree" ]; then
  files=$(git ls-files --cached --others --exclude-standard) || gate_die "cannot list the tree"
elif [ "$#" -gt 0 ]; then
  files=$(printf '%s\n' "$@")
else
  require_base
  files=$(changed_files) || gate_die "cannot list changed files against '$BASE'"
fi
files=$(printf '%s\n' "$files" | grep -vE "$skip" | while IFS= read -r f; do [ -f "$f" ] && echo "$f"; done)
targets=()
while IFS= read -r f; do [ -n "$f" ] && targets+=("$f"); done <<< "$files"   # bash 3.2: no mapfile
[ "${#targets[@]}" -gt 0 ] || { echo "QG-SAST-01: no files to scan"; exit 0; }

report="$(mktemp "${TMPDIR:-/tmp}/symbiont-semgrep.XXXXXX")" || gate_die "cannot create a temp file"
trap 'rm -f "$report"' EXIT
echo "QG-SAST-01 snapshot: $stamp"
uv run --no-sync semgrep scan --metrics=off --disable-version-check --quiet --json \
  --output "$report" --config "$PACKS" "${targets[@]}" >/dev/null \
  || gate_die "semgrep failed to run the registry packs"
uv run --no-sync python "$ROOT/scripts/gates/check_registry_findings.py" "$report"
