#!/usr/bin/env bash
# QG-SEC-03 data, transcript, weights and large-file path guard. Prevents a private dataset,
# transcript, model weight or run log from reaching the public repo
# (the repo boundary) and fails closed: it looks at every tracked and staged path, not only changed
# ones, because a published transcript cannot be un-published. No waiver.
#   check_paths.sh            tracked and staged paths of this repo
#   check_paths.sh tree DIR   every file under DIR (an exported tree: scripts/publish/check_export.sh)
# Names are read NUL-delimited and matched case-insensitively, one at a time, so a non-ASCII name,
# a space or an upper-case extension cannot slip past a pattern. A name with a
# control character, double quote or backslash is itself a finding: it cannot be handled safely.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

FIXTURE_MAX_BYTES=200000
LARGE_MAX_BYTES=1048576   # a dataset or weight shard is far above this; anything bigger needs a reason
# Allowlist for >1 MB files. results/offline-selection.json is per-task ids and numbers; its content
# is judged by QG-SEC-04 (shapes), so size alone is not a reason to refuse it.
LARGE_OK='^(uv\.lock|results/offline-selection\.json)$'
DATA_EXT='parquet|gguf|safetensors|bin|pt|pth|ckpt|onnx|npy|npz|h5|hdf5|arrow|feather|pkl|pickle|wad|pem|p12|pfx|jks|keystore|key|ndjson|csv|tsv|log|sqlite3?|db|zip|tar|tgz|gz|7z|traj|jsonl'
FORBIDDEN="(^|/)(data|runs)/|transcript|trajector|adapter_(model|config)|(^|/)id_(rsa|dsa|ecdsa|ed25519)|(^|/)\.env|\.($DATA_EXT)\$"
JSONL_OK='^tests/fixtures/.*\.jsonl$'
# dashboard/package.json and its lockfile are npm's pinned tooling manifests (QG-FE-01/03): two exact
# names, never a pattern, so any other dashboard JSON is still refused.
JSON_OK='^(tests/fixtures/|results/|dashboard/sample/|\.claude/).*\.json$|^(scripts/gates/baseline|\.gitleaks-baseline)\.json$|^dashboard/(package|package-lock)\.json$'
RESULTS_JSON_ONLY='^(results|dashboard/sample)/'
BINARY_OK='\.(png|jpe?g|gif|ico|woff2?|pdf)$'
# unsafe_name NAME: true when NAME holds a control character, a double quote or a backslash
unsafe_name() { [ "$1" != "$(printf '%s' "$1" | tr -d '\001-\037"\\')" ]; }
shopt -s nocasematch

tree=""
list=$(mktemp "${TMPDIR:-/tmp}/symbiont-paths.XXXXXX") || gate_die "cannot create a temp file"
trap 'rm -f "$list"' EXIT
if [ "${1:-}" = "tree" ]; then
  tree="${2:-}"; [ -d "$tree" ] || gate_die "check_paths.sh tree needs an existing directory"
  (cd "$tree" && find . -type f -print0) > "$list" || gate_die "cannot list $tree"
else
  { git ls-files -z; git diff --cached --name-only --diff-filter=ACMR -z; } > "$list" \
    || gate_die "cannot list tracked and staged paths"
fi

real() { if [ -n "$tree" ]; then echo "$tree/$1"; else echo "$1"; fi; }

# The tracked and staged lists overlap; dedupe by exact whole-name match (sort -u on NUL records),
# never by a substring test over a joined string: "a data/x.txt" must not hide "data/x.txt".
LC_ALL=C sort -z -u "$list" > "$list.u" || gate_die "cannot sort the path list"
mv "$list.u" "$list"

forbidden="" stray_json="" results_other="" oversized="" binaries="" unsafe=""
while IFS= read -r -d '' raw; do
  p="${raw#./}"
  if unsafe_name "$p"; then unsafe="$unsafe${p//[$'\001'-$'\037']/?}"$'\n'; continue; fi
  if [[ "$p" =~ $FORBIDDEN ]] && ! [[ "$p" =~ $JSONL_OK ]]; then forbidden="$forbidden$p"$'\n'; fi
  if [[ "$p" =~ \.json$ ]] && ! [[ "$p" =~ $JSON_OK ]]; then stray_json="$stray_json$p"$'\n'; fi
  if [[ "$p" =~ $RESULTS_JSON_ONLY ]] && ! [[ "$p" =~ \.json$ ]]; then results_other="$results_other$p"$'\n'; fi
  f=$(real "$p"); [ -f "$f" ] || continue
  size=$(wc -c < "$f")
  if [ "$size" -gt "$LARGE_MAX_BYTES" ] && ! [[ "$p" =~ $LARGE_OK ]]; then oversized="$oversized$p ($size bytes)"$'\n'; fi
  if [ "$size" -gt "$FIXTURE_MAX_BYTES" ] && [[ "$p" =~ ^tests/fixtures/ ]]; then
    oversized="$oversized$p ($size bytes, fixture limit $FIXTURE_MAX_BYTES: a dataset row renamed into fixtures?)"$'\n'
  fi
  if [ -s "$f" ] && ! grep -qI . "$f" && ! [[ "$p" =~ $BINARY_OK ]]; then binaries="$binaries$p"$'\n'; fi
done < "$list"

fail=0
report() { echo "QG-SEC-03: $1" >&2; printf '%s' "$2" >&2; fail=1; }
[ -z "$unsafe" ] || report "file names with a control character, double quote or backslash (cannot be checked safely):"$'\n' "$unsafe"
[ -z "$forbidden" ] || report "paths that must never be published (raw data, transcripts, trajectories, weights, adapters, keys, env files, run logs):"$'\n' "$forbidden"
[ -z "$stray_json" ] || report "json outside tests/fixtures/, results/ and dashboard/sample/ (counts and labels only live there):"$'\n' "$stray_json"
[ -z "$results_other" ] || report "results/ and dashboard/sample/ may hold .json files only (counts and labels, nothing else):"$'\n' "$results_other"
[ -z "$oversized" ] || report "files over the size limit (1 MB; fixtures 200 KB):"$'\n' "$oversized"
[ -z "$binaries" ] || report "binary files other than images, fonts and pdf (a weight or dataset under another name?):"$'\n' "$binaries"

[ "$fail" -eq 0 ] && echo "QG-SEC-03: OK"
exit "$fail"
