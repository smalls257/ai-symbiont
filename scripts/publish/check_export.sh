#!/usr/bin/env bash
# The publish check, run before the FIRST public push and before any release. Prevents Silent
# Fallback at the publish boundary: the per-commit gates look at diffs and at history against a
# baseline, so a file that was fine in review and is sensitive as shipped, or a finding hidden by
# the baseline, still reaches GitHub. This script exports what a push would publish (every file
# of HEAD, no history, no baseline) into a temp dir and runs every sensitive-data check on the
# EXPORTED files, using the gate scripts and configuration of the EXPORTED commit. Any finding
# exits non-zero; no waiver.
#
#   scripts/publish/check_export.sh        exit 0 clean, 1 findings, 2 cannot run
#
# How it cannot be blinded:
#   * the export is `checkout-index` of HEAD, not `git archive`, so `export-ignore` in
#     .gitattributes cannot hide a tracked file; a .gitattributes with export-ignore or
#     export-subst is itself a finding, and the exported file count must equal the commit's;
#   * the checks and their config (.gitleaks.toml, .semgrep/) come from the exported commit, and
#     the run is refused while a gate file differs from HEAD in the working copy, so an
#     uncommitted loosening cannot change the verdict on committed code.
#
# Checks (each names the Violation it prevents):
#   paths     QG-SEC-03  data, transcripts, weights, keys, env files, large and binary files
#   secrets   QG-SEC-01  gitleaks over every exported file: credentials, private IPs, hostnames,
#                        home paths, MAC addresses, e-mail addresses, phone numbers
#   terms     QG-SEC-05  the owner's own identifiers (terms file outside the repo)
#   results   QG-SEC-04  counts, ids and labels only in results/ and dashboard/sample/
#   egress    QG-SAST-02 no outbound HTTP outside src/symbiont/egress/; no prompt text in logs
# Commit your work first: uncommitted changes are not exported and are not checked.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../gates/lib.sh"

need_tool git "install git"
need_tool gitleaks "brew install gitleaks"
need_venv
need_tool uv "https://docs.astral.sh/uv/"
PY="$ROOT/.venv/bin/python"
# the same launcher the pinned-semgrep gate uses; .venv/bin/semgrep reports a different version
SEMGREP=(uv run --project "$ROOT" --no-sync semgrep)
[ -x "$PY" ] || gate_die "python missing in .venv (run: uv sync --group dev)"
need_py_tool semgrep

GATE_FILES=(scripts/gates scripts/publish scripts/hooks .claude/hooks .semgrep .gitleaks.toml
            .gitleaks-baseline.json .importlinter .gitattributes .naming-waivers.txt .lizard-whitelist.txt)
dirty=$(git status --porcelain=v1 -z -- "${GATE_FILES[@]}" | tr '\0' '\n') || gate_die "git status failed"
if [ -n "$dirty" ]; then
  echo "PUBLISH CHECK REFUSED: gate files differ from HEAD (commit or revert them; the check judges the committed gates):" >&2
  printf '%s\n' "$dirty" >&2
  exit 1
fi

work=$(mktemp -d -t symbiont-export) || gate_die "cannot create a temp dir"
trap 'rm -rf "$work"' EXIT
tree="$work/tree"; anchor="$work/anchor"
mkdir "$tree" "$anchor" || gate_die "cannot create $tree"
env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE git init -q "$anchor" || gate_die "cannot create the anchor repo"   # gate scripts anchor to a git root; the exported tree stays clean.
# A hook exports GIT_DIR: without `env -u`, init would rewrite the REAL repository's config (core.bare)
GIT_INDEX_FILE="$work/index" git read-tree HEAD || gate_die "git read-tree HEAD failed"
GIT_INDEX_FILE="$work/index" git checkout-index -a --prefix="$tree/" || gate_die "git checkout-index failed"
expected=$(git ls-tree -r -z --name-only HEAD | tr -cd '\0' | wc -c | tr -d ' ')
exported=$(find "$tree" \( -type f -o -type l \) | wc -l | tr -d ' ')
[ "$exported" -gt 0 ] || gate_die "the export is empty (a check of nothing is not a pass)"
echo "export: $exported files from $(git rev-parse --short HEAD)"

failed=""
step() {
  local id="$1" label="$2"; shift 2
  local output rc
  output=$("$@" 2>&1); rc=$?
  if [ "$rc" -eq 0 ]; then echo "ok    $id $label"; return; fi
  echo "FAIL  $id $label (exit $rc)"; printf '%s\n' "$output" | sed 's/^/      /'; failed="$failed $id"
}
in_anchor() { (cd "$anchor" && "$@"); }   # exported scripts, run from a git root that is not the tree

export_is_complete() {
  [ "$exported" -eq "$expected" ] || { echo "exported $exported files but HEAD has $expected"; return 1; }
  if git cat-file -e HEAD:.gitattributes 2>/dev/null \
     && git show HEAD:.gitattributes | grep -Eqi 'export-(ignore|subst)'; then
    echo ".gitattributes uses export-ignore or export-subst: archives of the repo would omit or rewrite files this check examined"
    return 1
  fi
}

gitleaks_findings() {
  local report="$work/gitleaks.json"
  gitleaks dir --config "$tree/.gitleaks.toml" --redact --no-banner --log-level error \
    --report-format json --report-path "$report" "$tree" >/dev/null 2>&1
  local rc=$?
  [ "$rc" -le 1 ] && [ -f "$report" ] || { echo "gitleaks could not scan the export (exit $rc)"; return 2; }
  "$PY" - "$report" "$tree" <<'PY'
import json, sys
found = json.load(open(sys.argv[1])) or []
for f in found:
    print(f"{f['RuleID']}: {f['File'].removeprefix(sys.argv[2] + '/')}:{f['StartLine']}")
sys.exit(1 if found else 0)
PY
}

check_results() {
  local files
  files=$(find "$tree/results" "$tree/dashboard/sample" -name '*.json' -type f -print0 2>/dev/null | tr '\0' '\n')
  [ -z "$files" ] && return 0
  printf '%s\n' "$files" | tr '\n' '\0' | xargs -0 "$PY" "$tree/scripts/gates/check_results_content.py"
}

# Rule paths ("/src/") are relative to the scan root, so scan from inside the exported tree.
semgrep_boundary() {
  [ -d "$tree/src" ] || { echo "the export has no src/ to scan (a check of nothing is not a pass)"; return 1; }
  local pinned installed
  pinned=$(tr -d '[:space:]' < "$tree/.semgrep/VERSION"); installed=$("${SEMGREP[@]}" --version 2>/dev/null | tail -n 1 | tr -d '[:space:]')
  [ "$pinned" = "$installed" ] || { echo "semgrep $installed installed, $pinned pinned in .semgrep/VERSION"; return 1; }
  (cd "$tree" && "${SEMGREP[@]}" scan --metrics=off --disable-version-check --quiet --error \
    --config "$tree/.semgrep/symbiont/egress.yaml" --config "$tree/.semgrep/symbiont/spark-privacy.yaml" .)
}

for needed in scripts/gates/check_paths.sh scripts/gates/check_private_terms.py scripts/gates/check_results_content.py \
              .gitleaks.toml .semgrep/VERSION .semgrep/symbiont/egress.yaml .semgrep/symbiont/spark-privacy.yaml; do
  [ -s "$tree/$needed" ] || gate_die "the exported commit has no $needed (a check without its config checks nothing)"
done

step QG-PUB-01 "export is complete, no export-ignore" export_is_complete
step QG-SEC-03 "paths, size and binary guard" in_anchor bash "$tree/scripts/gates/check_paths.sh" tree "$tree"
step QG-SEC-01 "gitleaks over the exported files" gitleaks_findings
step QG-SEC-05 "owner private terms" "$PY" "$tree/scripts/gates/check_private_terms.py" tree "$tree"
step QG-SEC-04 "results content" check_results
step QG-SAST-02 "egress and prompt-logging rules on src/" semgrep_boundary

if [ -n "$failed" ]; then echo "PUBLISH CHECK RED:$failed"; exit 1; fi
echo "PUBLISH CHECK GREEN"
